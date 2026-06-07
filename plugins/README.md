# Plugins

This directory is reserved for runtime-specific plugin guidance.

The public toolkit does not ship real plugins because plugin formats, permissions, and install locations vary by runtime. Add plugin manifests or pointers here only when they are generic, synthetic, and safe to publish.

Recommended layout for user-provided plugins:

```text
plugins/
  example-plugin/
    README.md
    manifest.example.json
```

Keep plugin documentation focused on structure, expected permissions, and installation notes. Store private credentials, endpoints, workspace paths, and deployment details outside this public repository.
