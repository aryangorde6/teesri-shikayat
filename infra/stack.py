"""The whole backend: one table, one bucket, the API Lambda behind a Function URL, and the tripwire
Lambda fed by DynamoDB Streams through an EventBridge Pipe."""
import json

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_pipes as pipes,
    aws_s3 as s3,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

TOKEN_PARAM = "/teesri/telegram/bot-token"
SECRET_PARAM = "/teesri/telegram/webhook-secret"
WARD_INBOX_PARAM = "/teesri/ward-inbox"  # optional; unset = the console test inbox
MAIL_FROM_PARAM = "/teesri/mail-from"
CONSOLE_TOKEN_PARAM = "/teesri/console-token"  # demo controls on the console


class TeesriStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs) -> None:
        super().__init__(scope, cid, **kwargs)

        s = ddb.AttributeType.STRING
        table = ddb.Table(
            self, "Table",
            partition_key=ddb.Attribute(name="PK", type=s),
            sort_key=ddb.Attribute(name="SK", type=s),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            stream=ddb.StreamViewType.NEW_IMAGE,
            time_to_live_attribute="ttl",
        )
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=ddb.Attribute(name="GSI1PK", type=s),
            sort_key=ddb.Attribute(name="GSI1SK", type=s),
        )

        bucket = s3.Bucket(
            self, "Media",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
        )

        code = lambda_.Code.from_asset("build")
        env = {
            "TABLE": table.table_name,
            "BUCKET": bucket.bucket_name,
            "TG_TOKEN_PARAM": TOKEN_PARAM,
            "TG_SECRET_PARAM": SECRET_PARAM,
            "BEDROCK_REGION": "ap-south-1",
            "MODEL_ID": "global.amazon.nova-2-lite-v1:0",
            "WARD_INBOX_PARAM": WARD_INBOX_PARAM,
            "MAIL_FROM_PARAM": MAIL_FROM_PARAM,
            "CONSOLE_TOKEN_PARAM": CONSOLE_TOKEN_PARAM,
            "DEMO_CLOCK": "1",  # labelled "demo clock" on screen
            "AGENT_MODE": "template",  # "agent" once Bedrock quota arrives
        }
        ssm_read = iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name="teesri/*")],
        )

        def backend_fn(cid: str, handler: str, concurrency: int) -> lambda_.Function:
            f = lambda_.Function(
                self, cid,
                runtime=lambda_.Runtime.PYTHON_3_13,
                architecture=lambda_.Architecture.ARM_64,
                handler=handler,
                code=code,
                memory_size=256,
                timeout=Duration.seconds(30),
                reserved_concurrent_executions=concurrency,  # cost guard
                environment=env,
            )
            table.grant_read_write_data(f)
            f.add_to_role_policy(ssm_read)
            return f

        fn = backend_fn("Api", "teesri.handler.main", 20)
        bucket.grant_read_write(fn)
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["transcribe:StartTranscriptionJob", "transcribe:GetTranscriptionJob", "polly:SynthesizeSpeech"],
            resources=["*"],
        ))
        bedrock = iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["arn:aws:bedrock:*:*:inference-profile/*", "arn:aws:bedrock:*::foundation-model/*"],
        )
        fn.add_to_role_policy(bedrock)

        # The tripwire: every new report (RPT# insert) -> Pipe -> deterministic rule. Nothing else reaches it.
        tripwire = backend_fn("Tripwire", "teesri.tripwire.main", 5)
        tripwire.add_to_role_policy(iam.PolicyStatement(actions=["polly:SynthesizeSpeech"], resources=["*"]))
        pipe_role = iam.Role(self, "PipeRole", assumed_by=iam.ServicePrincipal("pipes.amazonaws.com"))
        table.grant_stream_read(pipe_role)
        tripwire.grant_invoke(pipe_role)
        pipe = pipes.CfnPipe(
            self, "ReportsToTripwire",
            role_arn=pipe_role.role_arn,
            source=table.table_stream_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                dynamo_db_stream_parameters=pipes.CfnPipe.PipeSourceDynamoDBStreamParametersProperty(
                    starting_position="LATEST",
                    batch_size=10,
                    maximum_retry_attempts=3,
                    on_partial_batch_item_failure="AUTOMATIC_BISECT",
                ),
                filter_criteria=pipes.CfnPipe.FilterCriteriaProperty(filters=[pipes.CfnPipe.FilterProperty(
                    pattern=json.dumps({"eventName": ["INSERT"],
                                        "dynamodb": {"Keys": {"PK": {"S": [{"prefix": "RPT#"}]}}}}),
                )]),
            ),
            target=tripwire.function_arn,
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                lambda_function_parameters=pipes.CfnPipe.PipeTargetLambdaFunctionParametersProperty(
                    invocation_type="REQUEST_RESPONSE"),
            ),
        )
        pipe.node.add_dependency(pipe_role)  # the role's policy must exist before the Pipe validates it

        # Transcribe finished (or failed) -> same Lambda continues the voice note.
        events.Rule(
            self, "TranscribeDone",
            event_pattern=events.EventPattern(
                source=["aws.transcribe"],
                detail_type=["Transcribe Job State Change"],
                detail={"TranscriptionJobName": [{"prefix": "vn_"}],
                        "TranscriptionJobStatus": ["COMPLETED", "FAILED"]},
            ),
            targets=[targets.LambdaFunction(fn, retry_attempts=2)],
        )

        # The case: one Standard state machine per incident (execution name = incident id), one Lambda per task.
        case_fn = backend_fn("Case", "teesri.case.main", 10)
        bucket.grant_read_write(case_fn)
        case_fn.add_to_role_policy(iam.PolicyStatement(actions=["polly:SynthesizeSpeech", "ses:SendEmail"], resources=["*"]))
        case_fn.add_to_role_policy(bedrock)  # the Strands case agent (AGENT_MODE=agent)

        def step(name: str, step_id: str, result_path: str | None = None, wait: bool = False,
                 timeout_path: str | None = None, extra: dict | None = None) -> tasks.LambdaInvoke:
            payload = {"step": step_id, "inc_id": sfn.JsonPath.string_at("$.inc_id"), **(extra or {})}
            if wait:
                payload["token"] = sfn.JsonPath.task_token
            mode = ({"integration_pattern": sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN} if wait
                    else {"payload_response_only": True})
            return tasks.LambdaInvoke(
                self, name, lambda_function=case_fn, payload=sfn.TaskInput.from_object(payload),
                result_path=result_path or sfn.JsonPath.DISCARD,
                task_timeout=sfn.Timeout.at(timeout_path) if timeout_path else None, **mode,
            )

        prepare = step("PrepareCase", "prepare")
        ask = step("AskVolunteer", "ask_volunteer", "$.approval", wait=True, timeout_path="$.clock.approve_s")
        ring = step("FindRingHomes", "ring", "$.ring")
        warn_home = tasks.LambdaInvoke(
            self, "WarnHome", lambda_function=case_fn, payload_response_only=True,
            payload=sfn.TaskInput.from_object({"step": "warn_home", "inc_id": sfn.JsonPath.string_at("$.inc_id"),
                                               "hh_id": sfn.JsonPath.string_at("$.hh_id")}))
        warn_all = sfn.Map(
            self, "WarnEveryHome", items_path="$.ring.homes", max_concurrency=10, result_path=sfn.JsonPath.DISCARD,
            item_selector={"inc_id": sfn.JsonPath.string_at("$.inc_id"),
                           "hh_id": sfn.JsonPath.string_at("$$.Map.Item.Value")})
        warn_all.item_processor(warn_home)
        warned = step("Warned", "warned")
        notify = step("NotifyWardOffice", "notify_ward")
        await_reply = step("AwaitWardReply", "await_reply", "$.ward", wait=True, timeout_path="$.clock.ward_s")
        handle = step("HandleWardReply", "handle_reply", extra={"reply": sfn.JsonPath.object_at("$.ward")})
        ask_residents = step("AskResidents", "checkins", wait=True, timeout_path="$.clock.checkin_s")
        evaluate = step("EvaluateClosure", "evaluate", "$.eval")
        reopened = step("Reopened", "reopened")
        closed = step("ClosedAtTap", "closed")
        still_open = step("StillOpen", "still_open")
        next_window = sfn.Wait(self, "NextSupplyWindow", time=sfn.WaitTime.seconds_path("$.clock.round_gap_s"))

        ask.add_catch(step("MarkUnapproved", "unapproved"), errors=["States.Timeout"], result_path=sfn.JsonPath.DISCARD)
        await_reply.add_catch(step("MarkNoWardReply", "no_reply"), errors=["States.Timeout"], result_path=sfn.JsonPath.DISCARD)
        ask_residents.add_catch(evaluate, errors=["States.Timeout"], result_path=sfn.JsonPath.DISCARD)  # window over

        prepare.next(ask).next(
            sfn.Choice(self, "VolunteerApproved?")
            .when(sfn.Condition.boolean_equals("$.approval.approved", True),
                  ring.next(warn_all).next(warned).next(notify).next(await_reply))
            .otherwise(step("MarkHeld", "held")))
        await_reply.next(handle).next(ask_residents).next(evaluate).next(
            sfn.Choice(self, "WhatResidentsSay")
            .when(sfn.Condition.string_equals("$.eval.outcome", "REOPENED"), reopened.next(await_reply))
            .when(sfn.Condition.string_equals("$.eval.outcome", "CLOSED_AT_TAP"), closed)
            .when(sfn.Condition.number_less_than("$.eval.round", 3), next_window.next(ask_residents))
            .otherwise(still_open))

        machine = sfn.StateMachine(
            self, "CaseMachine", definition_body=sfn.DefinitionBody.from_chainable(prepare),
            state_machine_type=sfn.StateMachineType.STANDARD, timeout=Duration.days(30))
        machine.grant_start_execution(tripwire)
        machine.grant_task_response(fn)
        machine.grant_read(fn)  # console reset lists running cases...
        machine.grant_execution(fn, "states:StopExecution")  # ...and stops them
        for f in (fn, tripwire):
            f.add_environment("STATE_MACHINE_ARN", machine.state_machine_arn)

        url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        CfnOutput(self, "FunctionUrl", value=url.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "TripwireName", value=tripwire.function_name)
        CfnOutput(self, "CaseMachineArn", value=machine.state_machine_arn)
