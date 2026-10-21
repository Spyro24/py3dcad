# PY3DCAD translations

One JSON object per language, named after its locale code:

- `en.json`
- `de.json`
- `pt_BR.json`

Keys may be flat or nested; nested keys are addressed with dots:

```json
{
  "app": {
    "name": "PY3DCAD"
  },
  "file.new": "New Design"
}
```

```python
translator = Translator(language="de")
translator.translate("app.name")   # "PY3DCAD" (falls back to en.json)
translator.translate("file.new")   # "Neues Design"
```

Strings may contain `{placeholders}`:

```json
{
  "welcome": "Welcome, {name}!"
}
```

```python
translator.translate("welcome", name="Spyro")
```

Unknown keys are returned unchanged. The default and fallback language is `en`.
