# Single Sign-On (SSO) Configuration

## Supported Identity Providers
- Okta
- Azure AD
- Google Workspace
- Custom SAML 2.0

## Okta Setup
1. In Okta Admin Console, go to Applications > Add Application
2. Search for "CloudSync" and add it
3. Configure SAML settings:
   - Single sign on URL: https://app.cloudsync.io/sso/callback
   - Audience URI: https://app.cloudsync.io/sso/metadata
   - Name ID format: EmailAddress
4. Assign users/groups to the CloudSync app
5. In CloudSync Admin Console, go to Settings > SSO
6. Enter the Okta Metadata URL or upload the metadata XML
7. Click "Test Connection", then "Enable SSO"

## Azure AD Setup
1. In Azure Portal, go to Enterprise Applications > New Application
2. Create a non-gallery application named "CloudSync"
3. Configure Single Sign-On > SAML
4. Enter the same SSO URL and Audience URI as above
5. Download the Federation Metadata XML
6. Upload it to CloudSync Admin Console > Settings > SSO
7. Enable SSO

## Troubleshooting
- "SAML response invalid": Check clock sync on IdP and CloudSync (max 5 min skew)
- "User not found": Ensure the user exists in CloudSync with matching email
- "NameID format error": Set NameID format to EmailAddress in IdP settings
