# 🧠 Advanced Chat App API

Chat applications support **session persistence**, allowing previous
chat history to be used as context for responses. This can be applicable
for chatbot, customer service AI, etc.

------------------------------------------------------------------------

## 🏗️ Base URL

    http://localhost/v1

------------------------------------------------------------------------

## 🔐 Authentication

The Service API uses **API-Key** authentication.

> ⚠️ **Important:** Store your API key securely on the **server-side**
> only.\
> Do **not** share or store it on the client-side to prevent leakage.

**Header Example:**

``` http
Authorization: Bearer {API_KEY}
```

------------------------------------------------------------------------

## 💬 Send Chat Message

**Endpoint:**

    POST /chat-messages

### Example Request (cURL)

``` bash
curl -X POST 'http://localhost/v1/chat-messages' --header 'Authorization: Bearer {api_key}' --header 'Content-Type: application/json' --data-raw '{
  "inputs": {},
  "query": "What are the specs of the iPhone 13 Pro Max?",
  "response_mode": "streaming",
  "conversation_id": "",
  "user": "abc-123",
  "files": [
    {
      "type": "image",
      "transfer_method": "remote_url",
      "url": "https://cloud.dify.ai/logo/logo-site.png"
    }
  ]
}'
```

------------------------------------------------------------------------

## 🧩 Blocking Mode --- Example Response

``` json
{
  "event": "message",
  "task_id": "c3800678-a077-43df-a102-53f23ed20b88",
  "id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "message_id": "9da23599-e713-473b-982c-4328d4f5c78a",
  "conversation_id": "45701982-8118-4bc5-8e9b-64562b4555f2",
  "mode": "chat",
  "answer": "iPhone 13 Pro Max specs are listed here:...",
  "metadata": {
    "usage": {
      "prompt_tokens": 1033,
      "prompt_unit_price": "0.001",
      "completion_tokens": 128,
      "completion_unit_price": "0.002",
      "total_tokens": 1161,
      "total_price": "0.0012890",
      "currency": "USD",
      "latency": 0.7682
    },
    "retriever_resources": [
      {
        "dataset_name": "iPhone",
        "document_name": "iPhone List",
        "score": 0.98457545,
        "content": ""Model","Release Date","Display Size","Resolution","Processor","RAM","Storage","Camera","Battery","Operating System"..."
      }
    ]
  },
  "created_at": 1705407629
}
```

------------------------------------------------------------------------

## 🧾 Request Body Parameters

  -------------------------------------------------------------------------------
  Name                     Type              Description
  ------------------------ ----------------- ------------------------------------
  **query**                `string`          User input/question content.

  **inputs**               `object`          Contains variable key/value pairs
                                             for the App. Defaults to `{}`.

  **response_mode**        `string`          Response mode: `streaming`
                                             (recommended) or `blocking`.

  **user**                 `string`          Unique user identifier for session
                                             tracking.

  **conversation_id**      `string`          Continue conversation by passing the
                                             previous conversation ID.

  **files**                `array[object]`   List of attached files for
                                             multimodal input.

  **auto_generate_name**   `bool`            Auto-generate title (default
                                             `true`).

  **workflow_id**          `string`          (Optional) Specify a workflow
                                             version.

  **trace_id**             `string`          (Optional) Trace identifier for
                                             distributed tracing.
  -------------------------------------------------------------------------------

------------------------------------------------------------------------

## 🖼️ File Object Specification

  ------------------------------------------------------------------------
  Field                 Type            Description
  --------------------- --------------- ----------------------------------
  **type**              `string`        File type: `document`, `image`,
                                        `audio`, `video`, `custom`.

  **transfer_method**   `string`        `remote_url` or `local_file`.

  **url**               `string`        File URL (for `remote_url`
                                        method).

  **upload_file_id**    `string`        Upload ID (for `local_file`
                                        method).
  ------------------------------------------------------------------------

### Supported File Types

-   **Document:** TXT, MD, PDF, HTML, XLSX, DOCX, CSV, PPTX, XML, EPUB,
    etc.\
-   **Image:** JPG, PNG, GIF, SVG, WEBP\
-   **Audio:** MP3, M4A, WAV, WEBM\
-   **Video:** MP4, MOV, MPEG, WEBM\
-   **Custom:** Other formats

------------------------------------------------------------------------

## 🧠 Response Structure

### `ChatCompletionResponse` (Blocking)

  ------------------------------------------------------------------------
  Field                 Type            Description
  --------------------- --------------- ----------------------------------
  **event**             `string`        Always `"message"`.

  **task_id**           `string`        Request tracking ID.

  **message_id**        `string`        Unique message ID.

  **conversation_id**   `string`        Conversation ID.

  **answer**            `string`        AI response text.

  **metadata**          `object`        Includes `usage` and
                                        `retriever_resources`.

  **created_at**        `int`           Unix timestamp.
  ------------------------------------------------------------------------

------------------------------------------------------------------------

## 🔁 Streaming Mode (Server-Sent Events)

Each chunk starts with:

    data: {...}

### Common Event Types

  Event                 Description
  --------------------- ----------------------------------------------------
  `message`             Text chunk returned by the model.
  `message_file`        A generated file (e.g., image).
  `message_end`         Marks the end of streaming.
  `tts_message`         Speech synthesis (TTS) audio chunk (base64).
  `tts_message_end`     End of TTS audio stream.
  `message_replace`     Moderation-triggered message replacement.
  `workflow_started`    Workflow execution started.
  `node_started`        Node within workflow started.
  `node_finished`       Node within workflow finished (success/fail).
  `workflow_finished`   Workflow completed (success/fail).
  `error`               Error event, terminates stream.
  `ping`                Heartbeat ping every 10s to keep connection alive.

------------------------------------------------------------------------

## ⚙️ Error Codes

  -------------------------------------------------------------------------------------
  HTTP Code                 Error                           Description
  ------------------------- ------------------------------- ---------------------------
  **404**                   `conversation_not_exists`       Conversation does not
                                                            exist.

  **400**                   `invalid_param`                 Invalid parameter input.

  **400**                   `app_unavailable`               App configuration
                                                            unavailable.

  **400**                   `provider_not_initialize`       Missing model credentials.

  **400**                   `provider_quota_exceeded`       Model quota exceeded.

  **400**                   `model_currently_not_support`   Model currently
                                                            unavailable.

  **400**                   `workflow_not_found`            Specified workflow not
                                                            found.

  **400**                   `draft_workflow_error`          Draft workflow cannot be
                                                            used.

  **400**                   `workflow_id_format_error`      Invalid UUID format.

  **400**                   `completion_request_error`      Text generation failed.

  **500**                   `internal_server_error`         Internal system error.
  -------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 🧩 Notes for Developers

-   Use **`conversation_id`** to maintain chat sessions.
-   Prefer **streaming** mode for real-time responses.
-   Secure your **API key** and avoid exposing it on the client side.
-   For TTS responses, decode Base64 audio and play it directly.
