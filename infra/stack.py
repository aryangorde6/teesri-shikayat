"""The whole backend: one table, one bucket, one Lambda behind one Function URL."""
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_dynamodb as ddb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
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

        fn = lambda_.Function(
            self, "Api",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="teesri.handler.main",
            code=lambda_.Code.from_asset("build"),
            memory_size=256,
            timeout=Duration.seconds(30),
            reserved_concurrent_executions=20,  # cost guard for a public URL
            environment={
                "TABLE": table.table_name,
                "BUCKET": bucket.bucket_name,
                "TG_TOKEN_PARAM": TOKEN_PARAM,
                "TG_SECRET_PARAM": SECRET_PARAM,
                "BEDROCK_REGION": "ap-south-1",
                "MODEL_ID": "global.amazon.nova-2-lite-v1:0",
            },
        )
        table.grant_read_write_data(fn)
        bucket.grant_read_write(fn)
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name="teesri/*")],
        ))

        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["transcribe:StartTranscriptionJob", "transcribe:GetTranscriptionJob", "polly:SynthesizeSpeech"],
            resources=["*"],
        ))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["arn:aws:bedrock:*:*:inference-profile/*", "arn:aws:bedrock:*::foundation-model/*"],
        ))

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
