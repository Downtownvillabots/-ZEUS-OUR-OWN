# 🏙️ DOWNTOWN VILLA — Media Indexing Feature #1

## Modes

### Historical
Reply to the selected channel message and use `/index`.
The bot presents:

- 🎬 Movies
- 📺 Series
- 🎬📺 Both

The scanner moves backward toward older messages.

### Live
Configure:

```env
DATABASE_CHANNELS=-1001111111111,-1002222222222
LIVE_INDEXING_ENABLED=true
```

The bot listens for new media in all configured channels.

## MongoDB

```env
DATABASE_1_URI=mongodb+srv://...
MEDIA_DATABASE_URIS=mongodb+srv://db2...,mongodb+srv://db3...
MEDIA_DATABASE_ROTATION_MB=400
```

Database 1 is reserved for core bot data. Database 2+ are media databases.

The manager checks `dataSize + indexSize` and rotates before the configured
safe threshold. 400 MB is the initial recommended value for a 512 MB target;
adjust it after observing the actual Atlas metrics.

## Important integration note

This feature does not require the core bot to expose MongoDB internals.
Inject `MongoMediaRepository` into `MediaProcessor` from the application's
database bootstrap when connecting the production database.

Do not put bot secrets into this feature or into GitHub.
