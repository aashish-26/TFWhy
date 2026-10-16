resource "aws_instance" "user_data" {
  user_data = timestamp()
}

resource "aws_instance" "ami" {
  ami = data.aws_ami.base.id
}

resource "aws_instance" "random" {
  user_data = random_id.suffix.hex
}

resource "aws_instance" "indexed" {
  for_each = var.instances
  ami      = var.ami
}

resource "aws_instance" "unknown" {
  tags = {
    Name = "stable"
  }
}

resource "aws_instance" "data_source" {
  subnet_id = data.aws_subnet.selected.id
}

variable "instances" {
  type = set(string)
}

variable "ami" {
  type = string
}