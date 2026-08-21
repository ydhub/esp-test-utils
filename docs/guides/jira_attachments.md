# Jira attachments

Install the optional Jira client before using these commands:

```bash
pip install "esp-test-utils[jira]"
```

`esp-jira-att` resolves credentials in this order:

1. `CI_JIRA_TOKEN`, with optional `CI_JIRA_URL`.
2. `CI_JIRA_USERNAME` and `CI_JIRA_PASSWORD`, with optional `CI_JIRA_URL`.
3. `JIRA_TOKEN`, with optional `JIRA_URL`.
4. `JIRA_USERNAME` and `JIRA_PASSWORD`, with optional `JIRA_URL`.
5. The first available account file: `BOT_JIRA_ACCOUNT_FILE_PATH`,
   `./Account.JIRA.yml`, or `~/.config/Account.JIRA.yml`.

Account files are YAML mappings and may use either a token or username/password:

```yaml
url: https://jira.example.com
token: your-personal-access-token
```

```bash
# Upload a file or zip a directory before uploading it
esp-jira-att upload TEST-123 ./test.log
esp-jira-att upload TEST-123 ./evidence-directory

# Inspect attachments before downloading
esp-jira-att list TEST-123

# Download every attachment, or select one by filename or attachment ID
esp-jira-att download TEST-123 --dest ./artifacts
esp-jira-att download TEST-123 --name test.log --dest ./artifacts
esp-jira-att download TEST-123 --id 123456 --dest ./artifacts
```

Use `--server`, `--token`, and `--timeout` to override resolved settings for a
single command. Directory uploads are compressed to a zip archive and reject
archives larger than 20 MiB. When downloading all attachments, duplicate
filenames are suffixed instead of overwritten.
