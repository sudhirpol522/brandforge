# AWS deployment

This module creates a VPC, private ECS Fargate services, an internal Application Load Balancer,
RDS PostgreSQL, a private versioned S3 bucket, ECR repositories, Secrets Manager integration,
CloudWatch logs, health checks, deployment rollback, and API autoscaling.

The safe default is an internal ALB. Put an identity-aware gateway in front of it and pass only
validated tenant/user claims. Setting enable_public_demo to true is for a disposable portfolio
demo: it makes the ALB public and enables development-header authentication, so it must never
hold real brand assets.

## Apply

1. Build, scan, push, and digest-pin the API and worker images.
2. Store the OpenAI key in AWS Secrets Manager as the complete secret string.
3. Copy example.tfvars outside source control and set image digests and the secret ARN.
4. Run terraform init, terraform plan -out plan.bin, review the plan, then apply it.
5. Run the SQL migration in ../sql/001_tenant_rls.sql with separate application and worker
   database roles before accepting tenant data.
6. Configure HTTPS, WAF, an OIDC identity layer, backups, alarms, and an external telemetry
   backend for the target environment.

No secret value is a Terraform input. RDS generates its password in Secrets Manager, and ECS
injects the database password and OpenAI key at runtime.
