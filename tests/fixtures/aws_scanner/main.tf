terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region                      = var.aws_region
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

variable "aws_region" {
  description = "AWS region for the TFWhy test environment."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Prefix for test resources."
  type        = string
  default     = "tfwhy-lab"
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.micro"
}

variable "ami_id" {
  description = "Set a valid Linux AMI ID for the selected region before planning against AWS."
  type        = string
  default     = "ami-0123456789abcdef0"
}

variable "allowed_http_cidr" {
  description = "CIDR allowed to reach the demo HTTP listener. Public access is intentional for security-scanner testing."
  type        = string
  default     = "0.0.0.0/0"
}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name = "${var.project_name}-${random_id.suffix.hex}"
  common_tags = {
    Project     = var.project_name
    Environment = "tfwhy-test"
    ManagedBy   = "Terraform"
  }
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = "${local.name}-vpc" })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name}-igw" })
}

resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = "${var.aws_region}a"
  map_public_ip_on_launch = true
  tags                    = merge(local.common_tags, { Name = "${local.name}-public-a" })
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.42.2.0/24"
  availability_zone       = "${var.aws_region}b"
  map_public_ip_on_launch = true
  tags                    = merge(local.common_tags, { Name = "${local.name}-public-b" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = merge(local.common_tags, { Name = "${local.name}-public-rt" })
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# Intentionally public HTTP ingress for testing TFWhy's security findings.
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "Allow HTTP to the demo load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Intentionally public HTTP for scanner testing"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_http_cidr]
  }

  egress {
    description = "Allow outbound traffic for the demo"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-alb-sg" })
}

resource "aws_security_group" "instance" {
  name        = "${local.name}-instance-sg"
  description = "Allow HTTP only from the ALB security group"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from ALB only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Allow outbound traffic for the demo"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name}-instance-sg" })
}

# Set ami_id to a valid AMI in the chosen region before running a real plan.
resource "aws_instance" "web" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.instance.id]
  associate_public_ip_address = false

  root_block_device {
    encrypted   = false # Intentionally insecure for scanner testing.
    volume_type = "gp3"
  }

  user_data = <<-USERDATA
    #!/bin/bash
    echo "TFWhy test instance" > /tmp/tfwhy-test.txt
  USERDATA

  tags = merge(local.common_tags, { Name = "${local.name}-web" })
}

resource "aws_lb" "web" {
  name               = substr("${local.name}-alb", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  # access_logs intentionally omitted for scanner testing.
  tags = merge(local.common_tags, { Name = "${local.name}-alb" })
}

resource "aws_lb_target_group" "web" {
  name     = substr("${local.name}-tg", 0, 32)
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = merge(local.common_tags, { Name = "${local.name}-tg" })
}

resource "aws_lb_target_group_attachment" "web" {
  target_group_arn = aws_lb_target_group.web.arn
  target_id        = aws_instance.web.id
  port             = 80
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# Encryption and public-access-block settings are intentionally absent to test findings.
# Do not apply this test fixture unchanged.
resource "aws_s3_bucket" "logs" {
  bucket = "${local.name}-logs"
  tags   = merge(local.common_tags, { Name = "${local.name}-logs" })
}

resource "aws_iam_role" "firehose" {
  name = "${local.name}-firehose-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "firehose.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "firehose_s3" {
  name = "${local.name}-firehose-s3-write"
  role = aws_iam_role.firehose.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject"
      ]
      Resource = [
        aws_s3_bucket.logs.arn,
        "${aws_s3_bucket.logs.arn}/*"
      ]
    }]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "logs" {
  name        = "${local.name}-delivery"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.logs.arn
    prefix              = "firehose/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/"
    buffering_size      = 5
    buffering_interval  = 300
    compression_format  = "GZIP"
  }

  tags       = local.common_tags
  depends_on = [aws_iam_role_policy.firehose_s3]
}

# Additional intentionally unsafe resources for local TFWhy review testing.
# These examples contain no real credentials and must not be applied.
resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "logs_public_read" {
  bucket = aws_s3_bucket.logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadForScannerTesting"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.logs.arn}/*"
    }]
  })
}

resource "aws_iam_policy" "wildcard_test" {
  name = "${local.name}-wildcard-test"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}

resource "aws_db_instance" "public_test" {
  identifier                 = "${local.name}-db"
  allocated_storage          = 20
  engine                     = "postgres"
  engine_version             = "15.5"
  instance_class             = "db.t3.micro"
  db_name                    = "tfwhy"
  username                   = "tfwhy_test_admin"
  manage_master_user_password = true
  publicly_accessible        = true
  storage_encrypted          = false
  skip_final_snapshot        = true
  deletion_protection        = false
  tags                       = merge(local.common_tags, { Name = "${local.name}-db" })
}

resource "aws_network_acl" "public" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name}-public-nacl" })
}

resource "aws_network_acl_rule" "public_ssh" {
  network_acl_id = aws_network_acl.public.id
  rule_number    = 100
  egress         = false
  protocol       = "tcp"
  rule_action    = "allow"
  cidr_block     = "0.0.0.0/0"
  from_port      = 22
  to_port        = 22
}

resource "aws_network_acl_association" "public_a" {
  network_acl_id = aws_network_acl.public.id
  subnet_id      = aws_subnet.public_a.id
}

output "vpc_id" {
  description = "ID of the test VPC."
  value       = aws_vpc.main.id
}

output "load_balancer_dns_name" {
  description = "DNS name of the demo load balancer."
  value       = aws_lb.web.dns_name
}

output "s3_bucket_name" {
  description = "Name of the Firehose destination bucket."
  value       = aws_s3_bucket.logs.bucket
}

output "firehose_stream_name" {
  description = "Name of the demo Firehose delivery stream."
  value       = aws_kinesis_firehose_delivery_stream.logs.name
}
