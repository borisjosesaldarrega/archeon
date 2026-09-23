# Media

`src/archeon/media/` is the only media owner. It contains discovery, candidate matching, metadata, playback state, optional codecs, output-device selection and provider adapters. Provider and codec loading is lazy. Playback shutdown closes readers, decoder/player processes and watchers.

The old `MusicManager` behavior was compared before archival. Useful behavior was migrated; insecure TLS bypass, global mutable stream state, fixed-rate assumptions and continuous device polling were rejected. Commercial catalog completeness and licensed third-party services remain provider-dependent.
