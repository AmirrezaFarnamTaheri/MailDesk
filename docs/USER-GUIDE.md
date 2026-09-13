# User Guide

## 1. Recipients

Choose Excel/CSV or connect a Google account and load a Google Sheet. Confirm the detected worksheet/header row, then review suggested field mappings.

The preview supports row selection and campaign-only cell edits. Edits do not modify the original file.

## 2. Template

Choose or create a reusable template. Use placeholders, defaults and conditionals. Optional HTML, signature, snippets, attachments and inline images can be added here.

## 3. Personalization

Map optional Cc/Bcc/attachment columns, add Cc/Bcc templates, then render. Blocking errors must be fixed before a campaign can enter the queue.

Click a validation row or use the live-review arrows to inspect generated mail. To make a one-off correction, edit the current message in the review pane; the batch ID is recomputed.

## 4. Delivery

Choose:

- **Dry run** — queue execution with zero external side effects.
- **Browser drafts** — exact browser profile + verified Gmail `/u/N/` route.
- **Gmail drafts** — API-created drafts.
- **Send** — API send with typed confirmation.

Set pacing, an optional schedule, and duplicate protection.

## 5. Review & queue

Confirm message count, sender/route, timing and batch ID. Check the review box. Real sends also require exact typed confirmation.

## Queue

Use Queue to inspect progress, pause/resume, retry failed messages, cancel work, or expand a campaign to see every row.

## Browser routes

Open Accounts → Browser sender routes. Create one entry for each Gmail account path in each browser profile. For example:

```text
Chrome · Profile 1 · slot 0 · personal@example.com
Chrome · Profile 1 · slot 1 · work@example.com
```

Use **Verify** before browser processing. Never assume `/u/1/` is permanently tied to the same account after sign-in order changes.
