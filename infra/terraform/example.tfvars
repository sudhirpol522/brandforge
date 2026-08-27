aws_region         = "us-east-1"
name               = "brandforge"
environment        = "staging"
api_image           = "123456789012.dkr.ecr.us-east-1.amazonaws.com/brandforge-api@sha256:replace-me"
worker_image        = "123456789012.dkr.ecr.us-east-1.amazonaws.com/brandforge-worker@sha256:replace-me"
enable_public_demo  = false

# Supply an existing secret ARN at apply time; never write the API key in this file.
# openai_api_key_secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:brandforge/openai-..."
