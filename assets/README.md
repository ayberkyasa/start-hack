# assets/

Drop image/PDF files here that the agent may embed or attach.

- Accepted: PNG, JPG/JPEG, WebP, PDF. Max 5 MB each (Target API limit).
- Reference by EXACT filename. The agent sees the filename list and can:
  - embed an image in an HTML email/landing page: <img src="asset://logo.png">
  - attach a file by putting its filename in the plan's "attachments".
- Files are uploaded to POST /v1/assets on first use and reused across sessions.
- A filename in "attachments" that is NOT here is sent as a lure name only
  (no upload) to try to earn an "action" (attachment.opened).

Images (logos, banners, screenshots): the twin actually sees these rendered inside your HTML email or landing page. To display, they must have a real asset_id, so they genuinely have to be uploaded via POST /assets. This is the real purpose of the endpoint — and why putting ais_logo.png in assets/ with a matching name matters: if the model references it, it uploads and the twin sees it.

Attachments (PDF, docx, "invoice", "questionnaire"): the twin never sees the contents — only the filename. Opening one fires an attachment.opened event (the "action" win) purely from the name. So you do not need to upload a real PDF, and uploading one earns you nothing extra. The filename-only lure is the intended mechanic.