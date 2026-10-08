"""The whole backend: one table, one bucket, the API Lambda behind a Function URL, and the tripwire
Lambda fed by DynamoDB Streams through an EventBridge Pipe."""
import base64
import json
import pathlib

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    Fn,
    aws_dynamodb as ddb,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_pipes as pipes,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

TOKEN_PARAM = "/teesri/telegram/bot-token"
SECRET_PARAM = "/teesri/telegram/webhook-secret"
WARD_INBOX_PARAM = "/teesri/ward-inbox"  # optional; unset = the console test inbox
MAIL_FROM_PARAM = "/teesri/mail-from"
CONSOLE_TOKEN_PARAM = "/teesri/console-token"  # demo controls on the console
LLAMA = "b11505"  # llama.cpp release, official arm64 CPU build, checksum-pinned
LLAMA_ARM64_SHA256 = "adf1064ca125f42fd2f5a038346a2c6c0b58fe68bd3b21a55a825c9373f9a34a"


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

        # The self-hosted model (this account's Bedrock quota is 0): an open model in llama.cpp on one Graviton
        # instance. No inbound ports: requests come over SQS, answers go to the table (MODELRESP#), all via IAM.
        # It runs only when started (scenario.py model on) and stops itself after an idle hour.
        model_q = sqs.Queue(self, "ModelRequests", visibility_timeout=Duration.minutes(10),
                            retention_period=Duration.hours(1), encryption=sqs.QueueEncryption.SQS_MANAGED)
        model_file = ssm.StringParameter(self, "ModelFile", parameter_name="/teesri/model/file",
                                         string_value="gemma-4-E4B_q4_0-it.gguf")  # Google QAT build
        vm_role = iam.Role(self, "ModelRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                           managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")])
        bucket.grant_read_write(vm_role, "models/*")
        model_q.grant_consume_messages(vm_role)
        model_file.grant_read(vm_role)
        vm_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:PutItem"], resources=[table.table_arn],
            conditions={"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["MODEL#heartbeat", "MODELRESP#*"]}},
        ))
        vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)
        sg = ec2.SecurityGroup(self, "ModelSg", vpc=vpc, allow_all_outbound=True,
                               description="Teesri model: no inbound rules at all")
        worker = pathlib.Path(__file__).resolve().parent.parent.joinpath("model/worker.py").read_bytes()
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "set -euxo pipefail",
            "export DEBIAN_FRONTEND=noninteractive",
            "apt-get update && apt-get install -y --no-install-recommends python3-boto3 ca-certificates curl libgomp1",
            f"curl -fsSL -o /tmp/llama.tgz https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA}/llama-{LLAMA}-bin-ubuntu-arm64.tar.gz",
            f'echo "{LLAMA_ARM64_SHA256}  /tmp/llama.tgz" | sha256sum -c -',
            "mkdir -p /opt/llama /opt/teesri && tar -xzf /tmp/llama.tgz -C /opt/llama --strip-components=1",
            f"echo {base64.b64encode(worker).decode()} | base64 -d > /opt/teesri/worker.py",
            "cat > /etc/systemd/system/teesri-model.service <<'UNIT'",
            "[Unit]", "Description=Teesri self-hosted model", "After=network-online.target", "Wants=network-online.target",
            "[Service]",
            Fn.join("", ["Environment=AWS_REGION=", self.region, " BUCKET=", bucket.bucket_name,
                         " QUEUE_URL=", model_q.queue_url, " TABLE=", table.table_name]),
            "ExecStart=/usr/bin/python3 /opt/teesri/worker.py", "Restart=always", "RestartSec=5",
            "[Install]", "WantedBy=multi-user.target", "UNIT",
            "systemctl daemon-reload && systemctl enable --now teesri-model",
        )
        model_vm = ec2.Instance(
            self, "ModelVm",
            instance_type=ec2.InstanceType("c8g.4xlarge"),  # Graviton4, 16 cores, $0.43/h while running
            machine_image=ec2.MachineImage.from_ssm_parameter(
                "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id", cached_in_context=True),
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC), security_group=sg,
            role=vm_role, user_data=user_data, user_data_causes_replacement=True, require_imdsv2=True,
            block_devices=[ec2.BlockDevice(device_name="/dev/sda1", volume=ec2.BlockDeviceVolume.ebs(
                30, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True))],
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
            "AGENT_MODE": "agent",  # the Strands case agent; falls back to templates if no model answers (instance off)
            "MODEL_BACKEND": "selfhost",
            "MODEL_QUEUE_URL": model_q.queue_url,  # "bedrock" (Nova) or "selfhost" (open model on our EC2 instance)
        }
        ssm_read = iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name="teesri/*")],
        )

        def backend_fn(cid: str, handler: str, concurrency: int, timeout_s: int = 30) -> lambda_.Function:
            f = lambda_.Function(
                self, cid,
                runtime=lambda_.Runtime.PYTHON_3_13,
                architecture=lambda_.Architecture.ARM_64,
                handler=handler,
                code=code,
                memory_size=256,
                timeout=Duration.seconds(timeout_s),
                reserved_concurrent_executions=concurrency,  # cost guard
                environment=env,
            )
            table.grant_read_write_data(f)
            f.add_to_role_policy(ssm_read)
            return f

        fn = backend_fn("Api", "teesri.handler.main", 20, timeout_s=90)  # a voice note may wait on the model
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
        model_q.grant_send_messages(fn)

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
        case_fn = backend_fn("Case", "teesri.case.main", 10, timeout_s=300)  # agent goals on the CPU model
        bucket.grant_read_write(case_fn)
        case_fn.add_to_role_policy(iam.PolicyStatement(actions=["polly:SynthesizeSpeech", "ses:SendEmail"], resources=["*"]))
        case_fn.add_to_role_policy(bedrock)  # the Strands case agent (AGENT_MODE=agent)
        model_q.grant_send_messages(case_fn)

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
        CfnOutput(self, "ModelInstanceId", value=model_vm.instance_id)
