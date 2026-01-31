# ASICBOOST Support Patch for cpuminer-multi

## ⚠️ CRITICAL FINDING: The Problem is in the MINER, NOT P2Pool!

**P2Pool's ASICBOOST implementation is CORRECT!** Testing confirms:
- ✅ `mining.configure` is properly handled
- ✅ Response IDs match request IDs perfectly
- ✅ Version-rolling negotiation works correctly
- ✅ All JSON-RPC responses are valid

**The "Stratum answer id is not correct!" error is caused by buggy miner code** that doesn't properly handle unsolicited notifications (mining.notify, mining.set_difficulty) which have their own IDs.

## Purpose
Enable BIP320 version-rolling support in cpuminer-multi for **testing P2Pool ASICBOOST implementation**. This allows CPU miners to properly negotiate and use version-rolling, validating that the pool's ASICBOOST infrastructure works correctly.

**This patch includes the CRITICAL FIX for response ID matching** that most miners get wrong!

## Protocol Overview

### 1. Mining.Configure (Client → Pool)
```json
{
  "id": 2,
  "method": "mining.configure",
  "params": [
    ["version-rolling"],
    {
      "version-rolling.mask": "1fffe000",
      "version-rolling.min-bit-count": 2
    }
  ]
}
```

### 2. Pool Response
```json
{
  "id": 2,
  "result": {
    "version-rolling": true,
    "version-rolling.mask": "1fffe000"
  }
}
```

### 3. Mining.Submit with Version Bits
```json
{
  "id": 4,
  "method": "mining.submit",
  "params": [
    "worker_name",
    "job_id",
    "extranonce2",
    "ntime",
    "nonce",
    "version_bits"  // NEW: 6th parameter for version rolling
  ]
}
```

## Implementation Changes

### File: util.c (stratum_handle_response)

**CRITICAL FIX**: Miners must properly handle response IDs and unsolicited notifications!

The problem with many miners: They expect ALL messages to have sequential IDs matching requests. 
This is WRONG! The stratum protocol has:
- **Request/Response pairs** - These have matching IDs (subscribe=1, configure=2, authorize=3)
- **Unsolicited notifications** - These have random IDs (mining.notify, mining.set_difficulty)

```c
// CORRECT response handling - match by ID, not order
static bool stratum_handle_response(struct stratum_ctx *sctx, const char *s, int expected_id, json_t **result_out)
{
    json_t *val, *id_json, *result, *error;
    json_error_t err;
    int received_id;
    bool ret = false;

    val = JSON_LOADS(s, &err);
    if (!val) {
        applog(LOG_ERR, "JSON decode failed(%d): %s", err.line, err.text);
        return false;
    }

    // Check if this is a response (has 'result' or 'error') or a notification (has 'method')
    const char *method = json_string_value(json_object_get(val, "method"));
    if (method) {
        // This is an unsolicited notification (mining.notify, mining.set_difficulty)
        // Handle it in the normal handler and continue waiting for our response
        json_decref(val);
        return false;  // Not the response we're looking for
    }

    // This is a response - check ID
    id_json = json_object_get(val, "id");
    if (!id_json || !json_is_integer(id_json)) {
        applog(LOG_ERR, "Response missing or invalid ID");
        json_decref(val);
        return false;
    }

    received_id = json_integer_value(id_json);
    if (received_id != expected_id) {
        applog(LOG_WARNING, "Response ID mismatch: expected %d, got %d", expected_id, received_id);
        json_decref(val);
        return false;  // Keep looking
    }

    // Check for error
    error = json_object_get(val, "error");
    if (error && !json_is_null(error)) {
        applog(LOG_ERR, "Server returned error: %s", 
               json_string_value(json_object_get(error, "message")));
        json_decref(val);
        return false;
    }

    // Extract result
    result = json_object_get(val, "result");
    if (result && result_out) {
        *result_out = json_incref(result);
    }

    json_decref(val);
    return true;
}

// Read lines until we find response with matching ID
static json_t *stratum_wait_for_response(struct stratum_ctx *sctx, int expected_id, int timeout_sec)
{
    json_t *result = NULL;
    time_t start = time(NULL);
    
    while (time(NULL) - start < timeout_sec) {
        if (!socket_full(sctx->sock, 1)) {
            continue;  // No data yet, keep waiting
        }

        char *line = NULL;
        size_t len = 0;
        ssize_t nread;
        
        // Read one line
        FILE *sockfp = fdopen(dup(sctx->sock), "r");
        if (!sockfp) {
            applog(LOG_ERR, "fdopen failed");
            break;
        }
        
        nread = getline(&line, &len, sockfp);
        fclose(sockfp);
        
        if (nread > 0) {
            // First, handle any notifications (mining.notify, mining.set_difficulty)
            stratum_handle_method(sctx, line);
            
            // Then check if this is our response
            if (stratum_handle_response(sctx, line, expected_id, &result)) {
                free(line);
                return result;  // Found it!
            }
        }
        
        free(line);
    }
    
    applog(LOG_ERR, "Timeout waiting for response id=%d", expected_id);
    return NULL;
}
```

Add configure negotiation function with CORRECT response handling:

```c
// CORRECTED: Properly wait for response by ID
bool stratum_configure(struct stratum_ctx *sctx)
{
    char s[512];
    json_t *result = NULL;
    bool ret = false;
    int request_id = sctx->next_id++;

    // Request version-rolling with 0x1fffe000 mask (13 bits)
    snprintf(s, sizeof(s),
        "{\"id\": %d, \"method\": \"mining.configure\", \"params\": "
        "[[\"version-rolling\"], "
        "{\"version-rolling.mask\": \"1fffe000\", "
        "\"version-rolling.min-bit-count\": 2}]}\n",
        request_id);

    applog(LOG_INFO, "Requesting ASICBOOST support...");
    
    if (!stratum_send_line(sctx, s)) {
        applog(LOG_ERR, "Failed to send mining.configure");
        return false;
    }

    // CRITICAL: Use the new response handler that correctly matches by ID
    result = stratum_wait_for_response(sctx, request_id, 10);
    if (!result) {
        applog(LOG_WARNING, "No response to mining.configure - pool may not support it");
        sctx->version_rolling = false;
        return true;  // Not fatal - continue without ASICBOOST
    }

    // Parse the result
    json_t *vr = json_object_get(result, "version-rolling");
    json_t *mask = json_object_get(result, "version-rolling.mask");
    
    if (json_is_true(vr) && mask) {
        const char *mask_str = json_string_value(mask);
        sctx->version_rolling = true;
        sctx->version_mask = strtoul(mask_str, NULL, 16);
        applog(LOG_INFO, "✓ ASICBOOST enabled: mask=0x%08x (%d bits)", 
               sctx->version_mask, __builtin_popcount(sctx->version_mask));
        ret = true;
    } else {
        applog(LOG_INFO, "Pool does not support version-rolling");
        sctx->version_rolling = false;
        ret = true;
    }

    json_decref(result);
    return ret;
}
```

### File: miner.h (struct stratum_ctx)

Add version-rolling state:

```c
struct stratum_ctx {
    char *url;
    
    struct {
        char *user;
        char *pass;
    } cred;

    // ... existing fields ...

    // ASICBOOST / Version Rolling (BIP320)
    bool version_rolling;      // Is version-rolling enabled?
    uint32_t version_mask;     // Mask from pool (e.g., 0x1fffe000)
    uint32_t version_counter;  // Counter for version bits
};
```

### File: util.c (stratum_subscribe)

Call configure after successful subscribe:

```c
bool stratum_subscribe(struct stratum_ctx *sctx)
{
    // ... existing subscription code ...

    ret = true;

    // NEW: Try to negotiate version-rolling
    if (!stratum_configure(sctx)) {
        applog(LOG_WARNING, "mining.configure failed, continuing without ASICBOOST");
        sctx->version_rolling = false;
    }

out:
    // ... existing cleanup ...
}
```

### File: util.c (stratum_gen_work)

Generate version bits when creating work:

```c
bool stratum_gen_work(struct stratum_ctx *sctx, struct work *work)
{
    // ... existing code ...

    // Apply version bits if version-rolling is enabled
    if (sctx->version_rolling && sctx->version_mask) {
        // Use counter to vary version bits across different work units
        uint32_t version_bits = (sctx->version_counter++ & 0x1fff) << 13;
        work->data[0] = (work->data[0] & ~sctx->version_mask) | 
                        (version_bits & sctx->version_mask);
    }

    // ... rest of existing code ...
}
```

### File: util.c (stratum_submit_work)

Include version_bits in submit:

```c
static bool stratum_submit_work(struct stratum_ctx *sctx, struct work *work)
{
    char *str = NULL;
    json_t *val, *res;
    char s[345];
    bool ret = false;

    // Extract version bits from work data
    uint32_t nversion = swab32(work->data[0]);
    uint32_t version_bits = nversion & sctx->version_mask;

    // ... existing code to build ntime, nonce, etc ...

    if (sctx->version_rolling && sctx->version_mask) {
        // Submit with version_bits parameter (6 params)
        sprintf(s,
            "{\"method\": \"mining.submit\", \"params\": "
            "[\"%s\", \"%s\", \"%s\", \"%s\", \"%s\", \"%08x\"], \"id\":%u}",
            rpc_user, work->job_id, xnonce2str, ntimestr, noncestr,
            version_bits, sctx->next_id++);
    } else {
        // Standard submit (5 params)
        sprintf(s,
            "{\"method\": \"mining.submit\", \"params\": "
            "[\"%s\", \"%s\", \"%s\", \"%s\", \"%s\"], \"id\":%u}",
            rpc_user, work->job_id, xnonce2str, ntimestr, noncestr,
            sctx->next_id++);
    }

    // ... rest of submission code ...
}
```

## Root Cause Analysis

**The "Stratum answer id is not correct!" error is a MINER BUG, not a P2Pool bug!**

Testing shows P2Pool responds correctly:
- `mining.subscribe` (id=1) → Response with id=1 ✓
- `mining.configure` (id=2) → Response with id=2 ✓  
- `mining.authorize` (id=3) → Response with id=3 ✓

The problem: Many miners **incorrectly assume all messages have sequential IDs**. They don't properly distinguish between:

1. **Request/Response pairs** - MUST have matching IDs
   - `mining.subscribe`, `mining.configure`, `mining.authorize` 
   - Pool MUST echo the request ID in the response

2. **Unsolicited notifications** - Have random/generated IDs
   - `mining.notify` (new work)
   - `mining.set_difficulty` (difficulty adjustment)
   - These are NOT responses, so IDs don't match requests

**Buggy miner logic:**
```c
// WRONG - assumes next message has expected ID
send_request(id=2);
response = read_one_line();  // Might be mining.notify with id=123456!
if (response.id != 2)
    error("ID mismatch!");  // FALSE ALARM!
```

**Correct logic:**
```c
// RIGHT - keeps reading until finding matching response
send_request(id=2);
while (timeout_not_reached) {
    msg = read_one_line();
    if (is_notification(msg)) {
        handle_notification(msg);  // Process mining.notify, set_difficulty
        continue;  // Keep looking
    }
    if (is_response(msg) && msg.id == 2) {
        return msg;  // Found it!
    }
}
```

## Testing the Implementation

### 1. Build Modified cpuminer-multi
```bash
cd cpuminer-multi
./build.sh
```

### 2. Test Against P2Pool
```bash
./cpuminer -a x11 \
  -o stratum+tcp://192.168.86.244:7903 \
  -u XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6 \
  -p x \
  -D  # Debug mode to see protocol messages
```

### 3. Expected Output (CORRECTED)
```
[2025-12-09 12:34:56] Stratum connection to 192.168.86.244:7903
[2025-12-09 12:34:56] Stratum session id: ae6812eb4cd7735a302a8a9dd95cf71f
[2025-12-09 12:34:56] Requesting ASICBOOST support...
[2025-12-09 12:34:56] ✓ ASICBOOST enabled: mask=0x1fffe000 (13 bits)
[2025-12-09 12:34:56] Stratum difficulty set to 0.01
[2025-12-09 12:34:57] thread 0: 2048 hashes, 9.8 MH/s
```

### 4. Verify on P2Pool Side
P2Pool logs should show:
```
>>>Authorize: XsFe6mGpLM3R6ZieYJXhsmGyYg8jn3Lth6 from 192.168.86.245
```

### 5. Verify Protocol with Python Test Script
```bash
python3 /tmp/test_stratum2.py
```

Should show:
```
=== Testing P2Pool Stratum (Sequential) ===
>>> [1] mining.subscribe
✓ Found response for id=1
>>> [2] mining.configure
✓ Found response for id=2
>>> [3] mining.authorize
✓ Found response for id=3

=== Summary ===
Subscribe: ✓
Configure: ✓
Authorize: ✓
```

## Benefits for Testing

1. **Protocol Validation**: Confirms P2Pool correctly implements BIP320
2. **Debugging Tool**: Helps identify stratum protocol issues
3. **Development Aid**: Allows testing without expensive ASIC hardware
4. **Community Resource**: Others can validate their P2Pool forks
5. **Educational**: Shows how version-rolling actually works

## Performance Impact

For CPU miners, version-rolling has **zero performance benefit** - it's purely for testing the protocol. The version bits are varied across different work units, but this doesn't provide any efficiency gain on CPUs (unlike ASICs with midstate optimization).

## Compatibility

- **Backward compatible**: Works with pools that don't support version-rolling
- **Graceful degradation**: If `mining.configure` fails, miner continues normally
- **Standard compliant**: Follows BIP320/BIP310 specifications exactly

## References

- BIP320: https://github.com/bitcoin/bips/blob/master/bip-0320.mediawiki
- BIP310: https://github.com/bitcoin/bips/blob/master/bip-0310.mediawiki
- P2Pool Stratum: `/home/user0/Github/p2pool-dash/p2pool/dash/stratum.py`
