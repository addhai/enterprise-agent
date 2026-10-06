# Troubleshooting Guide

## SDK Initialization 403 Error

If your SDK initialization returns a 403 error:

1. **Check API Key**: Go to Console > Developer Settings. Verify the key is active and not expired. Regenerate if needed.

2. **Check Domain Whitelist**: Go to Console > Developer Settings > Domain Whitelist. Add your application's domain (e.g., app.example.com). Note: localhost is automatically whitelisted for development.

3. **Check CORS Configuration**: If using a web browser, ensure your server sends the correct CORS headers:
   ```
   Access-Control-Allow-Origin: https://your-app.com
   Access-Control-Allow-Headers: Authorization, Content-Type
   ```

4. **SDK Version Compatibility**: Run `pip show cloudsync` to check your version. Versions before v2.0 are deprecated and will return 403 errors.

## Sync Stuck at "Processing"

If sync is stuck in "Processing" state for more than 10 minutes:

1. Check the sync queue at Console > Sync Jobs
2. Look for files larger than your plan's limit
3. Cancel stuck jobs and retry in smaller batches
4. If the issue persists, check the provider status page for outages

## High Memory Usage

The desktop client may use significant memory with large sync sets:
1. Limit the number of folders being synced
2. Enable "Selective Sync" to pick specific subfolders
3. Exclude temporary files and build directories in settings

## Connection Timeout

For connection timeout errors:
1. Check your firewall allows outbound connections on port 443
2. Verify proxy settings in CloudSync Desktop > Preferences > Network
3. Test connection: `curl -I https://api.cloudsync.io/v1/health`
4. If behind a corporate proxy, configure proxy settings in the desktop app
