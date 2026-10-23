"""assisted-publisher: human-in-the-loop KDP title setup.

Hard rules, enforced in code rather than by convention:
- the browser is always visible (headless only against a local mock page)
- the tool never types passwords or one-time codes and never touches CAPTCHAs; it waits for you
- every KDP step stops for your review before 'Save and Continue'
- the tool never clicks Publish; you do
- KDP's weekly limit (2 new titles per format) is checked before a title is created
"""
