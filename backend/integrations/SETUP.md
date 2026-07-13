# Client integrations — setup call checklist

Everything is built. On the call we only gather the client's credentials/IDs, put
them in `.env`, restart, and verify. Until then all integrations are OFF and the
app runs normally.

Verify status any time: `GET /api/integrations/status`

---

## What happens once it's on

1. A video is uploaded to the editing machine named after a script (e.g.
   "Let's go get coffee").
2. **On upload** — we find the CPS card whose title matches that name and mark it
   in-progress. We never create cards; we only update existing ones.
3. **On render finish** — the finished cut is delivered to the matching card and
   the card is marked ready.

Matching ignores case, punctuation, and file extension:
`"Let's Go Get Coffee.mov"` → matches a card titled `Let's go get coffee`.

## Delivery mode — pick one (`NOTION_DELIVERY_MODE`)

- **`notion_upload`** — the video is uploaded straight into the Notion card and
  plays inline. Best when the whole review/approve/download loop lives in Notion.
  Requires a **paid Notion plan** (free workspaces cap uploads at 5 MB; our videos
  are ~50 MB, handled via multi-part upload). No Google Drive needed.
- **`drive_link`** (default) — video hosted on Google Drive, a permanent shareable
  link goes on the card. Best when the video needs to be shared/reused outside
  Notion. Works on any Notion plan.
- **`both`** — Drive for a permanent link AND a native inline copy in Notion.

---

## Notion — what to collect on the call

1. **Create an internal integration** at https://www.notion.so/my-integrations
   → copy its **Internal Integration Secret** → `NOTION_API_KEY`
2. In Notion, open the CPS database → **Connections → add the integration** (so it
   has access).
3. Copy the **database ID** from its URL → `NOTION_CPS_DATABASE_ID`
   (the 32-char id between the workspace slug and the `?v=`).
4. Look at the database's columns with them and map:
   - `NOTION_STATUS_PROPERTY` — the name of their status column (e.g. `Status`)
   - `NOTION_STATUS_EDITING` — the value to set on upload (e.g. `Editing`)
   - `NOTION_STATUS_READY` — the value to set when done (e.g. `Ready`)
   - `NOTION_VIDEO_PROPERTY` — a URL column to hold the Drive link (e.g. `Video`)
   (Status mapping is optional — if we skip it, we still match cards and attach the
   video link; we just won't flip a status.)

## Google Drive — what to collect on the call

Layout: one shared **root** folder. The machine auto-creates `<Client>/Edited/`
under it per creator, so nothing gets mixed up and there's zero per-client setup.

```
Root (shared with the service account)
├── Jordan Blake/Edited/   <- his finished cuts land here automatically
├── Adan/Edited/
└── ...
```

1. In Google Cloud Console → create a **service account** → create a **JSON key**.
   Set `GOOGLE_SERVICE_ACCOUNT_FILE` to its path (or paste into `GOOGLE_SERVICE_ACCOUNT_JSON`).
2. Enable the **Google Drive API** for that project.
3. In the client's Drive, create ONE root folder and **share it with the service
   account's email** (`name@project.iam.gserviceaccount.com`) as **Editor**.
4. Copy that root folder's ID from its URL → `GDRIVE_ROOT_FOLDER_ID`.

That's it — client names in the machine become the subfolder names automatically.
A finished "Jordan Blake" render lands in `Jordan Blake/Edited/`.

Install the Drive libraries once (already in requirements.txt):
`pip install google-api-python-client google-auth`

Since we're going Drive-only (client has no paid Notion plan), leave all
`NOTION_*` vars unset — the delivery mode stays `drive_link` and Notion is skipped.

---

## After entering the values

1. Restart the backend.
2. `GET /api/integrations/status` → both should read `"configured": true`.
3. Test: put a dummy card in the CPS DB titled `Test Clip`, upload a short video
   named `Test Clip`, run it, and confirm the card gets the Drive link + status.
