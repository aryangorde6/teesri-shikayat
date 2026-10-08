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
)
from constructs import Construct

TOKEN_PARAM = "/teesri/telegram/bot-token"
SECRET_PARAM = "/teesri/telegram/webhook-secret"


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
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["arn:aws:bedrock:*:*:inference-profile/*", "arn:aws:bedrock:*::foundation-model/*"],
        ))

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

        url = fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        CfnOutput(self, "FunctionUrl", value=url.url)
        CfnOutput(self, "TableName", value=table.table_name)
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "TripwireName", value=tripwire.function_name)
