# Ticket Resolver pitch ideas

## One-minute interview pitch

I built Ticket Resolver to learn how retrieval-augmented generation (RAG) works on a real support problem. Imagine an employee asks in August, “How long did I have to submit my June expense?” In my Northwind demo, the deadline changed from 30 days to 60 on July 1. Both versions contain a clause about expenses. Only the June version answers the question.

I’ve built the part that prepares those policies. A background worker parses each document into clauses, an editor confirms who each rule applies to, and the system records when each version was in effect.

Next I’m building the retriever. It’ll filter by country, worker type, and event date, then combine keyword and semantic search to find the right clause. I’ll test it with questions where an outdated policy or another country’s rule looks like a good match. Success means returning the exact clause that applies to that person.

## Two product pitches to test

### For a support lead at a multi-country HR or staffing platform

“When a worker asks about leave, how long does your agent spend checking the handbook, the country policy, and the local annex? I’m building a way to bring the applicable clause and its effective date straight into the agent’s review. Could we try it against a small set of anonymized tickets you’ve already resolved?”

For a pilot, ask the team to mark the expected clause for each ticket. Compare how often agents pick it and how long verification takes with their current workflow and with the proposed lookup. Include cases where the team itself needs clarification.

### For the person who maintains company policies

“When you publish a new policy, how do you check which locations it covers and which older rules it replaces? I can show you a policy review flow that keeps both versions, flags possible overlaps, and shows coverage by location and topic. Could we walk through your last policy change and see where this would have helped?”

Use the existing Northwind demo for the walkthrough. Publish the July expenses revision and inspect where the June version ends. Then open the German leave policy and its Bavaria-only annex. Ask the editor which checks they already have and which still take manual work.

## What I can show today

- **Built:** document upload, parsing, human tag review, effective dates, version publication, and a coverage map.
- **Planned:** ticket-time retrieval, cited answer generation, verification, and human handoff. Retrieval quality and time savings still need to be measured.
- **Commercial question:** would a team use clause lookup or policy review often enough to pay for it? The two pitches are ways to investigate that question.

[Implementation progress](PROGRESS.md) · [Retrieval plan and evaluation targets](PLAN.md)
