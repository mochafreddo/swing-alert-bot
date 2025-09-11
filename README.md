# swing-alert-bot

A lightweight Telegram bot that sends swing trading alerts (market close/open) using daily indicators. Runs on AWS Lambda + EventBridge + S3, configured via AWS SSM Parameter Store.

## Telegram Chat Whitelist

- Parameter: set `${PARAM_PREFIX}allowed_chat_ids` in AWS SSM to restrict who can use/receive the bot.
- Format: CSV (`"12345,67890,@myfriend"`) or JSON array string (`"[12345, -67890, \"@myfriend\"]"`). Numeric IDs or `@usernames` are supported.
- Add/update (SecureString):
  - `aws ssm put-parameter --name "/${PROJECT}/${ENV}/allowed_chat_ids" --type SecureString --value "12345,67890" --overwrite`
- Remove someone: edit the value (remove that ID/handle) and overwrite with the updated list.
- Verify current value:
  - `aws ssm get-parameter --name "/${PROJECT}/${ENV}/allowed_chat_ids" --with-decryption --query Parameter.Value --output text`
- Effect: changes take effect on the next Lambda invocation (runners and poller read the parameter each run).

For more details, see `TECHNICAL_DESIGN.md` (Chat Whitelist) and `infra/terraform/README.md` (Terraform secrets).

