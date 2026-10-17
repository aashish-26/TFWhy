# Synthetic static-analysis input. It must never be applied to infrastructure.

resource "aws_iam_policy" "broad" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:*"]
      Resource = "*"
    }]
  })
}

resource "aws_security_group" "egress" {
  egress {
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_network_acl_rule" "public_ssh" {
  egress      = false
  rule_action = "allow"
  protocol    = "tcp"
  cidr_block  = "0.0.0.0/0"
  from_port   = 22
}
