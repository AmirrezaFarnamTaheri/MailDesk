# User Guide

On a fresh install, MailDesk opens a short guided tour. You can replay it any time with **Quick tour** in the sidebar.

## 1. Recipients

Load an Excel/CSV file or a Google Sheet. Confirm the worksheet, header row and recipient-email column. MailDesk suggests common mappings automatically.

Use **More recipient options** only when you need Cc/Bcc columns, filtering, sorting or a row limit. You can select rows and make campaign-only cell edits without changing the original spreadsheet.

## 2. Message

Start with the built-in **General message** template or create your own. Use placeholders such as `{{Name|there}}`, optional conditions, snippets, HTML, signatures and attachments as needed. **Placeholder mapping** lets a reusable token such as `{{Name}}` read from any spreadsheet column, even when the source header has a different name. The live sheet stays beside the message preview so you can compare source values with the rendered message row by row.

## 3. Check

Choose **Check messages** to generate the personalized result for every selected row. Fix blocking errors before continuing.

Use the preview on the right or open a validation row to inspect individual messages. One-off edits can be made directly in the preview before the campaign is queued.

## 4. Delivery

Choose one delivery mode:

- **Dry run** — build and validate the queue without sending.
- **Browser compose** — open reviewed drafts in a configured browser sender.
- **Gmail drafts** — create drafts through a connected Gmail account.
- **Send email** — send through a connected Gmail account.

Campaign name, schedule, pacing and duplicate handling are optional.

## 5. Review

Confirm the message count, delivery mode, sender and timing. Live sending requires one typed confirmation: `SEND N`, where `N` is the number of messages.

## Queue

Use **Queue** to inspect progress, pause or resume work, retry failed messages, cancel a campaign, and inspect row-level results.

If Gmail returns an uncertain result during a draft or send operation, MailDesk pauses the affected item instead of guessing. Check Gmail, then mark the item as completed or not completed before resuming.

## Browser senders

Open **Senders → Browser senders** and choose a browser profile. MailDesk reads that profile and, when Chromium has cached the signed-in Google session, lists Gmail accounts in browser order so the account index and email can be filled automatically. Click **Rescan browsers** after signing in or changing accounts; manual account-index/email entry remains available as a fallback.

```text
Chrome · Profile 1 · account 0 · personal@example.com
Chrome · Profile 1 · account 1 · work@example.com
```

Use **Verify** before browser processing. The account index follows Gmail's signed-in account order, so verify again if that order changes or the verification expires.
