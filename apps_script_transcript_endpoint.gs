// Add this file to the existing Apps Script project that already contains
// extractVideoId(url) and getTranscript(videoId).
// Set TRANSCRIPT_API_SECRET under Project Settings > Script Properties.

function doPost(e) {
  try {
    const payload = JSON.parse((e.postData && e.postData.contents) || "{}");
    verifyTranscriptRequest(payload);

    const videoId = extractVideoId(String(payload.url || ""));
    if (!videoId) {
      throw new Error("Invalid YouTube URL.");
    }

    const transcript = getTranscript(videoId);
    if (!transcript || !String(transcript).trim()) {
      throw new Error("No transcript was returned for this video.");
    }
    return transcriptJsonResponse({ success: true, transcript: String(transcript) });
  } catch (error) {
    return transcriptJsonResponse({ success: false, error: String(error.message || error) });
  }
}

function verifyTranscriptRequest(payload) {
  const secret = PropertiesService.getScriptProperties().getProperty("TRANSCRIPT_API_SECRET");
  if (!secret) {
    throw new Error("TRANSCRIPT_API_SECRET is not configured.");
  }

  const timestamp = Number(payload.timestamp || 0);
  const nonce = String(payload.nonce || "");
  const url = String(payload.url || "").trim();
  const suppliedSignature = String(payload.signature || "").toLowerCase();
  const now = Math.floor(Date.now() / 1000);
  if (!timestamp || Math.abs(now - timestamp) > 300) {
    throw new Error("Transcript request expired.");
  }
  if (!nonce || nonce.length < 20 || !url || !suppliedSignature) {
    throw new Error("Transcript request is incomplete.");
  }

  const nonceKey = "transcript_nonce_" + nonce;
  const cache = CacheService.getScriptCache();
  if (cache.get(nonceKey)) {
    throw new Error("Transcript request has already been used.");
  }

  const canonical = timestamp + "\n" + nonce + "\n" + url;
  const digest = Utilities.computeHmacSha256Signature(canonical, secret);
  const expectedSignature = digest.map(function(value) {
    return ("0" + ((value + 256) % 256).toString(16)).slice(-2);
  }).join("");
  if (!constantTimeEquals(expectedSignature, suppliedSignature)) {
    throw new Error("Transcript request signature is invalid.");
  }
  cache.put(nonceKey, "1", 600);
}

function constantTimeEquals(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index++) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function transcriptJsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
