output "api_load_balancer_dns" {
  description = "Internal by default. Public only when enable_public_demo is explicitly true."
  value       = aws_lb.api.dns_name
}

output "asset_bucket" {
  value = aws_s3_bucket.assets.bucket
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "database_secret_arn" {
  value     = local.database_secret_arn
  sensitive = true
}

output "api_ecr_repository" {
  value = aws_ecr_repository.api.repository_url
}

output "worker_ecr_repository" {
  value = aws_ecr_repository.worker.repository_url
}
