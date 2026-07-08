We want to make a lightweight browser based checklist-type app that can track stickers in the Panini 2026 FIFA World Cup collection - which ones the user has already stuck in their book, which ones they still need, and which ones they have duplicates of.

The collection consists of stickers for each of the 48 competing nations, with 20 stickers per nation.  These are numbered 1-20 for each nation, preceded with a three-letter abbreviation.  You should calculate what these are and confirm them with me before committing to them in any way.

There are further generic stickers with prefix FWC - there are 19 of these, numbered 1-19.  

There are also further stickers as part of a promotion with Coca Cola with prefix CC - there are 12 of these, numbered 1-12.

Additionally there is a sticker number 00.

The app should present a simple interface from which we can quickly click or tap a sticker from the overall checklist when it is stuck in the book.  The app should use a colour coded system, in which each sticker we've got is highlighted in green, and any gaps remain grey or black.  If we have a duplicate of a sticker, it should be added to a separate list so we can easily see our duplicates, and have the ability to remove them from that list as and when we trade the duplicate to another person.

We want this to be a secure multi-user system, so we will need a login.

For the backend we wish to use gel data (formerly know as edgedb). You should create a schema based on the requirements.  When you need to propose or perform a migration, stop and ask me before going any further.

We should use python for scripting. Any packages you need to install should be done via uv. We need to use the ip address 192.168.1.170 and port 8003 for any servers as other ports are already in use. 

We should use tailwindcss and html for the front end. Create a dir called templates to store these in. Use jinja for the templating, and ensure you have a base.html file and content related fragments for each route, or view.

We want to use the correct project structure, so ensure that we adequately split functionality into routers and services. We need the code to be strictly typed, so ensure that pydantic is used to enforce that. 

We also need strict testing as we go along. Ensure that tests are adequately created for routers and services. 

Break these requirements down into a detailed plan on how you will achieve this, and show me the plan. You should save the plan in a file in the root dir, and call it "implementation1.md".

