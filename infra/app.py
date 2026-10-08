import os

import aws_cdk as cdk

from stack import TeesriStack

app = cdk.App()
TeesriStack(app, "Teesri", env=cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="ap-south-1",
))
cdk.Tags.of(app).add("project", "teesri-shikayat")
app.synth()
