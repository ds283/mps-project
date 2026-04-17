## SUMMARY

This task implements UI elements and routes allowing users to link their accouunts to a Box account.

You wlil need to use the `boxsdk` library to interface with the Box API.

### DATABASE MIGRATIONS

Please add fields `User.box_access_token` (string), `User.box_refresh_token` (string), `User.box_token_valid` (boolean),
`User.box_updated_at` (datetime) to the `User` model. `box_updated_at` should default to `datetime.now()` and have an
`onupdate` handler that resets its time.

### USER INTERFACE

Please add an action button to the shared `_online_services.html` template that links to the Box OAuth2 login page,
allowing users to link their Box account. Add discreet Box branding logos if these can be found in FontAwesome.
Assume that the Box Client ID is stored in the Flask configuration key `BOX_CLIENT_ID`, and the Box Client Secret is
stored in the Flask configuration key `BOX_CLIENT_SECRET`. These will be set as environmentn variables in the
`docker-compose.yml` file.

The OAuth 2 redirect URI should be set to `/oauth2/box-callback`. You may need to generate a new blueprint for this
route.

The `box_token_valid` field should be set to `True` if the refresh token is still valid, since that can always be used
to update the current access token. If `box_token_valid` is `False`, please surface this to the user with a notification
on the `_online_services.html` template indicating that the linked Box account is logged out. In this case they should
be given the option to link their Box account again by relaunchign the OAuth2 flow.

If `box_token_valid` is `True`, a "Successfully linked" notification should be displayed to the user.
