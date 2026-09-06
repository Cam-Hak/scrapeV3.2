## Scenario
- Need to gather article data from a large number of sources on the internet
- article data includes:
  1. Headline
  2. Date
  3. Body Text / Description

## Goal
- Using an api key for Haiku model to find where the headline, date, and body text live in the html
- Program should work for thousands of sites
- Requests to these sites should use a webdriver to load javascript content and look as human like as possible
- Use a webdriver that can bypass cloudflare
- assume no websites will be added if their robots.txt won't allow it

## Structure
- **Stay as bare bones and simple as possible**
- There should be a queue of sites that need a "recipe"
  - for now this can just be a csv
- We pass a site to the haiku model so it can find out where to point the program to the three important pieces of data (the recipe)
- Store the recipe in a lightweight internal db like sqlite or json
- When program runs on sites that have their recipe, it will be able to gather the data and put that data into a msql db (the schema will be given in db directory)

**Use codebase-design skill for implementation and planning**
**Use grill-me skill for planning**
**Use research skill to come up with best methods of implementation**
**Use superpowers while coding**
**Use code reviewer after each part of the code is written**
