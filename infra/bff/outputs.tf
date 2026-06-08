output "instance_id" {
  value = aws_instance.bff.id
}

output "public_ip" {
  value = aws_instance.bff.public_ip
}

output "ssm_tunnel_command" {
  description = "Open the private console at http://localhost:8000/ui/ via SSM port-forward."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.bff.id} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"8000\"],\"localPortNumber\":[\"8000\"]}'"
}

output "ssm_shell_command" {
  description = "Open an interactive shell on the box."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.bff.id}"
}
