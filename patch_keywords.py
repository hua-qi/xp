with open("src/server.py", "r") as f:
    content = f.read()

content = content.replace('                    "keywords": exp.metadata.keywords,', '                    "keywords": [],')

with open("src/server.py", "w") as f:
    f.write(content)

with open("src/cloud_providers.py", "r") as f:
    content = f.read()

content = content.replace('                    "keywords": exp.metadata.keywords,', '                    "keywords": [],')
content = content.replace('                keywords=metadata.get("keywords", []),', '                # keywords field removed')

with open("src/cloud_providers.py", "w") as f:
    f.write(content)
