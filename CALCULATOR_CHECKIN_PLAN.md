# Calculator check-in submission

Fork-only planning branch: docs/calculator-checkin-plan. Do not merge this branch
into the upstream feature PR. Implementation: feat/calculator-checkin-button.

## Decisions

- Add Submit This Check-in to the private /calculate_tier result and show the
  selected tier, the maximum of calorie and time tiers.
- Submit directly using the authenticated calculator owner's Discord ID.
  Discord bot messages cannot be authored by the user's account.
- Save first, then publish @user Tn check-in in the configured check-in channel.
  Keep bot-authored messages excluded from the ordinary message parser.
- Share save and medal-response functions with typed check-ins. Use the saved
  check-in ID and database medal owner/previous-holder IDs for every medal mention;
  never infer medal ownership from the confirmation message author.
- Preserve earned, stolen, surpassed-record replies, medal reactions, high-tier
  reactions, and the existing opening-roundup suppression policy.
- Bind the button to its owner, expire results after 10 minutes and on a local
  date change, and disable it after a successful save. Serialize repeated clicks.
- Validate the challenger, current week, and challenge membership at submission.
- Separate save errors from Discord/medal errors. Once saved, never retry insertion
  merely because confirmation or medal delivery failed. Tell the user what saved.
- No production DB or command-registry writes during development testing.

## Implementation and validation

1. Extract shared save and medal feedback code without parsing bot confirmations.
2. Add the calculator result view and button with validation and duplicate guards.
3. Test maximum-tier choice, owner and expiry checks, duplicate clicks, DB failure,
   post-save notification failure, and earned/stolen/self-surpassed medal mentions
   on a bot-authored public confirmation.
4. Run relevant existing tests. Verify the real UI with local DB and bot-testing
   channel when the development runtime is available.

The UTC rollover fix remains independent in PR #67. This feature should not
silently incorporate that pending PR or change roundup scheduling.
