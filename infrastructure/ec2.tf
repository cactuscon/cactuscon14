data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["amazon"] # Canonical
}

resource "aws_eip" "cactuscon-web" {
  tags = {
    Name = "cactuscon-web"
  }
}

resource "aws_instance" "cactuscon-web" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t4g.micro"

  key_name               = aws_key_pair.deployer.key_name
  vpc_security_group_ids = [aws_security_group.web-server.id]

  iam_instance_profile = aws_iam_instance_profile.cc14-web.name

  subnet_id  = aws_subnet.cactuscon.id
  private_ip = "10.14.0.101"

  root_block_device {
    encrypted   = true
    volume_size = 60
  }

  tags = {
    Name = "cactuscon-badge-web"
  }

  user_data = file("scripts/web-bootstrap.sh")
  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_eip_association" "cactuscon-web" {
  instance_id   = aws_instance.cactuscon-web.id
  allocation_id = aws_eip.cactuscon-web.id
}

resource "aws_instance" "cactuscon-backend" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t4g.micro"

  key_name               = aws_key_pair.deployer.key_name
  vpc_security_group_ids = [aws_security_group.backend-server.id]

  subnet_id                   = aws_subnet.cactuscon.id
  private_ip                  = "10.14.0.102"
  associate_public_ip_address = true

  root_block_device {
    encrypted   = true
    volume_size = 80
  }

  tags = {
    Name = "cactuscon-badge-api"
  }

  lifecycle {
    ignore_changes = [ami]
  }
}
