data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  resource_name = "${var.name}-${var.environment}"
  azs           = slice(data.aws_availability_zones.available.names, 0, 2)
  common_tags   = {
    Application = "BrandForge"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
  worker_image        = var.worker_image != "" ? var.worker_image : var.api_image
  model_provider      = var.openai_api_key_secret_arn != "" ? "openai" : "deterministic"
  database_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
  database_secrets   = [
    {
      name      = "DB_PASSWORD"
      valueFrom = "${local.database_secret_arn}:password::"
    }
  ]
  api_secrets = concat(
    local.database_secrets,
    var.openai_api_key_secret_arn != "" ? [
      {
        name      = "OPENAI_API_KEY"
        valueFrom = var.openai_api_key_secret_arn
      }
    ] : []
  )
  task_environment = [
    { name = "BRANDFORGE_ENV", value = var.environment },
    { name = "BRANDFORGE_DEV_AUTH", value = tostring(var.enable_public_demo) },
    { name = "DB_HOST", value = aws_db_instance.main.address },
    { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
    { name = "DB_USER", value = aws_db_instance.main.username },
    { name = "DB_NAME", value = aws_db_instance.main.db_name },
    { name = "OBJECT_STORE_PROVIDER", value = "s3" },
    { name = "S3_BUCKET", value = aws_s3_bucket.assets.bucket },
    { name = "S3_REGION", value = var.aws_region },
    { name = "MODEL_PROVIDER", value = local.model_provider },
    { name = "OPENAI_TEXT_MODEL", value = var.text_model },
    { name = "OPENAI_VISION_MODEL", value = var.vision_model },
    { name = "OPENAI_IMAGE_MODEL", value = var.image_model },
    { name = "ALLOWED_ORIGINS", value = var.allowed_origins },
    { name = "OTEL_SERVICE_NAME", value = "brandforge-api" }
  ]
  worker_environment = [
    { name = "BRANDFORGE_ENV", value = var.environment },
    { name = "DB_HOST", value = aws_db_instance.main.address },
    { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
    { name = "DB_USER", value = aws_db_instance.main.username },
    { name = "DB_NAME", value = aws_db_instance.main.db_name }
  ]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = local.resource_name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  for_each = { for index, az in local.azs : tostring(index) => az }

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, tonumber(each.key))
  map_public_ip_on_launch = true

  tags = { Name = "${local.resource_name}-public-${each.key}" }
}

resource "aws_subnet" "private" {
  for_each = { for index, az in local.azs : tostring(index) => az }

  vpc_id            = aws_vpc.main.id
  availability_zone = each.value
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, tonumber(each.key) + 10)

  tags = { Name = "${local.resource_name}-private-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"

  depends_on = [aws_internet_gateway.main]
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = values(aws_subnet.public)[0].id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "random_id" "bucket" {
  byte_length = 4
}

resource "aws_s3_bucket" "assets" {
  bucket = "${local.resource_name}-assets-${random_id.bucket.hex}"
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    id     = "expire-noncurrent"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_policy" "assets" {
  bucket = aws_s3_bucket.assets.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.assets.arn,
        "${aws_s3_bucket.assets.arn}/*"
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_security_group" "database" {
  name_prefix = "${local.resource_name}-db-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.tasks.id]
  }
}

resource "aws_db_subnet_group" "main" {
  name       = local.resource_name
  subnet_ids = values(aws_subnet.private)[*].id
}

resource "aws_db_instance" "main" {
  identifier                   = local.resource_name
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.database_instance_class
  allocated_storage            = var.database_allocated_storage_gb
  max_allocated_storage        = var.database_allocated_storage_gb * 4
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "brandforge"
  username                     = "brandforge_admin"
  manage_master_user_password  = true
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.database.id]
  publicly_accessible          = false
  backup_retention_period      = var.environment == "production" ? 14 : 7
  deletion_protection          = var.environment == "production"
  skip_final_snapshot          = var.environment != "production"
  performance_insights_enabled = true
  auto_minor_version_upgrade   = true
  apply_immediately            = false
}

resource "aws_ecs_cluster" "main" {
  name = local.resource_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.resource_name}-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "worker" {
  name                 = "${local.resource_name}-worker"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.resource_name}/api"
  retention_in_days = var.environment == "production" ? 90 : 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.resource_name}/worker"
  retention_in_days = var.environment == "production" ? 90 : 30
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.resource_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-runtime-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = compact([local.database_secret_arn, var.openai_api_key_secret_arn])
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.resource_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task_assets" {
  name = "tenant-asset-store"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.assets.arn
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.assets.arn}/*"
      }
    ]
  })
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.resource_name}-alb-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.enable_public_demo ? ["0.0.0.0/0"] : [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name_prefix = "${local.resource_name}-tasks-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "api" {
  name               = substr(local.resource_name, 0, 32)
  internal           = !var.enable_public_demo
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = (
    var.enable_public_demo
    ? values(aws_subnet.public)[*].id
    : values(aws_subnet.private)[*].id
  )
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = substr("${local.resource_name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 20
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.resource_name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "api"
    image       = var.api_image
    essential   = true
    environment = local.task_environment
    secrets     = local.api_secrets
    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name                   = "api"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.api.arn
  desired_count          = var.api_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = values(aws_subnet.private)[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.resource_name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "outbox-worker"
    image       = local.worker_image
    essential   = true
    command     = ["python", "-m", "apps.worker.main"]
    environment = local.worker_environment
    secrets     = local.database_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  }])
}

resource "aws_ecs_service" "worker" {
  name                   = "outbox-worker"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.worker.arn
  desired_count          = var.worker_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = values(aws_subnet.private)[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 10
  min_capacity       = var.api_desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${local.resource_name}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
