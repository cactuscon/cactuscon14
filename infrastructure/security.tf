resource "aws_key_pair" "deployer" {
  key_name   = "cc14-rx13-hive-cactuscon"
  public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDVJfiQFIMyZP5a5l32lIHVL9NUmcvt5VsLdhLycFxwy1lhPkaYgbU+UdBy/tgKha7N0dUkwav0XoPl2IDgO83tZqZEedYJIRDf5UBEiq/HeEwKDg2yNKgSMGehLFSoUDuQ7OC1aPcXz8YsmK/bjHT/a2r/oVxMMCDSfH3Co0tYi9dZGagyeZw5zB0BQS123TYWY1jhrcGJIF/TcVvjGOri1YOcM3VvC9YzWfODGtkXrH+4znnl5xPLE6YNBf0JlablAf2yqQSwyjOl7mY7TuH3BqO/eXzkYCELYrhNtJqEUr0zlOMOxFvyAAMCSufzeVOmEkxx9m0cZaJ/ZpDbv+bPPyEOsaqGNTyYD/KabZam840EFw9AXFTVPYcb9UFYYwtC+/dJH90WcXSUKwBlnnuVroyqP8MV5PjW2Lp6paFP/DS415StcO3aDtI04hcNZfeyHvmAV8TY/wDiiQwQAjx++YqbPNkssMhD8QRQ3CBDjTM/axhxL7jTB2QV0YzHm8jvfkUbXGfwdEpbzK+UD7skG4I9M4fsEX2ptGWZ2byQs6Oli8kXbALSmTukwb4Nm95jbRTxB5UDAuUBPTdhubKbj/l5s6uQdQXBQKqMxmPPjcIInpBZrPtQADMy4tE/RmoKEnj+V/gtCbNJAQazXbCBg8wLVV0H5v3ltdrcn6fiew== rx13@dev"
}

resource "aws_security_group" "web-server" {
  name        = "cc14-allow_tls"
  description = "Allow TLS inbound traffic"
  vpc_id      = aws_vpc.cactuscon.id

  ingress {
    description      = "its fine probably"
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description      = "Plain from all"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description      = "TLS from all"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "cactuscon-web"
  }
}



# resource "aws_security_group" "mqtt-server" {
#   name        = "cc14-allow_mqtt"
#   description = "Allow MQTT associated inbound traffic"
#   vpc_id      = aws_vpc.cactuscon.id

#   ingress {
#     description      = "its fine probably"
#     from_port        = 22
#     to_port          = 22
#     protocol         = "tcp"
#     cidr_blocks      = ["0.0.0.0/0"]
#     ipv6_cidr_blocks = ["::/0"]
#   }

#   ingress {
#     description = "Plain from internal"
#     from_port   = 8000
#     to_port     = 8000
#     protocol    = "tcp"
#     cidr_blocks = ["10.13.0.100/32"]
#   }

#   ingress {
#     description      = "MQTT from all"
#     from_port        = 8883
#     to_port          = 8883
#     protocol         = "tcp"
#     cidr_blocks      = ["0.0.0.0/0"]
#     ipv6_cidr_blocks = ["::/0"]
#   }

#   egress {
#     from_port        = 0
#     to_port          = 0
#     protocol         = "-1"
#     cidr_blocks      = ["0.0.0.0/0"]
#     ipv6_cidr_blocks = ["::/0"]
#   }

#   tags = {
#     Name = "cactuscon-mqtt"
#   }
# }

resource "aws_security_group" "backend-server" {
  name        = "cc14-backend_server"
  description = "Allow backend services and outbound"
  vpc_id      = aws_vpc.cactuscon.id

  ingress {
    description = "its fine probably"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  ingress {
    description = "Plain from internal"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "cactuscon-api"
  }
}