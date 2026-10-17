# Synthetic import proposal shape. It must never be applied to infrastructure.
terraform {
  required_version = ">= 1.5"
}

import {
  to = aws_s3_bucket.logs
  id = "example-logs"
}

resource "aws_s3_bucket" "logs" {
  bucket = "example-logs"
}
