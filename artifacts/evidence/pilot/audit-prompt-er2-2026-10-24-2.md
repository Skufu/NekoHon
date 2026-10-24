Audit 40 candidate finetune rows for a local book-answering model.

Each row is one Socratic exchange. The model must answer the FINAL question by
copying one sentence from the passages, then add one plain line of gloss. For
`premise_trap` rows the correct answer is exactly `Not in this book.`

For each row decide KEEP or DROP, and give a code.

DROP when any of these holds:
- wrong_subject: the answer addresses the history question or some other topic, not the final question
- unsupported: the cited sentence, read plainly, does not support the gloss
- history_not_needed: class is entity_relation or simplify, and the answer would be equally correct with the history removed
- trap_answered: class is premise_trap, but the passages do contain the thing asked about
- refusal_missing: class is not premise_trap, but the answer is a refusal
- wrong_relation: class is entity_relation, and the answer does not connect the named entity to the section topic

Do not check quote spelling; that is verified separately.

Reply with one line per row, no preamble, no code fences:
<id> <KEEP|DROP> <code|ok> | <short reason>


## entity_relation-11  class=entity_relation  book=fde  section='Additional Resources'
history:
User: togaf defines data architecture as what
Book: [Ch. 3] "A description of the structure and interaction of the enterprise’s major types and sources of data, logical data assets, physical data assets, and data management resources."
TOGAF says data architecture explains how an organization's data is organized and how different data parts work together.
final question: How does Test Data Quality connect to the sentence you quoted?
passage ch03-106 <-- target section:
Additional Resources
“Test Data Quality at Scale with Deequ” by Dustin Lange et al.

“Three-Tier Architecture” by IBM Education

TOGAF framework website

“The Top 5 Data Trends for CDOs to Watch Out for in 2021” by Prukalpa

“240 Tables and No Documentation?” by Alexey Makhotkin

“The Ultimate Data Observability Checklist” by Molly Vorwerck

“Unified Analytics: Where Batch and Streaming Come Together; SQL and Beyond” Apache Flink Roadmap

“UtilityVsStrategicDichotomy” by Martin Fowler

“What Is a Data Lakehouse?” by Ben Lorica et al.

“What Is Data Architecture? A Framework for Managing Data” by Thor Olavsrud

“What Is the Open Data Ecosystem and Why It’s Here to Stay” by Casber Wang

“What’s Wrong with MLOps?” by Laszlo Sragner

“What the Heck Is Data Mesh” by Chris Riccomini

“Who Needs an Architect” by Martin Fowler

“Zachman Framework” Wikipedia page

1 The Open Group, TOGAF Version 9.1, https://oreil.ly/A1H67.

2 Gartner Glossary, s.v. “Enterprise Architecture (EA),” https://oreil.ly/SWwQF.

3 EABOK Consortium website, https://eabok.org.

4 Jeff Haden, “Amazon Founder Jeff Bezos
answer: [Ch. 3] "Test Data Quality at Scale with Deequ” by Dustin Lange et al."
This is a suggested reading about checking data quality.

## entity_relation-12  class=entity_relation  book=fde  section='Principle 9: Embrace FinOps'
history:
User: what does finops help a data team do
Book: [Ch. 3] "FinOps is an evolving cloud financial management discipline and cultural practice that enables organizations to get maximum business value by helping engineering, finance, technology, and business teams to collaborate on data-driven spending decisions."
FinOps helps teams work together to make smart spending choices for better business results.
final question: How does FinOps Foundation connect to the sentence you quoted?
passage ch03-039 <-- target section:
Principle 9: Embrace FinOps
Let’s start by considering a couple of definitions of FinOps. First, the FinOps Foundation offers this:16

FinOps is an evolving cloud financial management discipline and cultural practice that enables organizations to get maximum business value by helping engineering, finance, technology, and business teams to collaborate on data-driven spending decisions.

In addition, J. R. Sorment and Mike Fuller provide the following definition in Cloud FinOps:17

The term “FinOps” typically refers to the emerging professional movement that advocates a collaborative working relationship between DevOps and Finance, resulting in an iterative, data-driven management of infrastructure spending (i.e., lowering the unit economics of cloud) while simultaneously increasing the cost efficiency and, ultimately, the profitability of the cloud environment.
answer: [Ch. 3] "First, the FinOps Foundation offers this:16"
The FinOps Foundation is the source of the definition quoted in the previous answer.

## entity_relation-13  class=entity_relation  book=fde  section='Principle 6: Build Loosely Coupled Systems'
history:
User: What is loosely coupled systems?
Book: [Ch. 3] "Systems are broken into many small components"
Systems are divided into small parts.
final question: How does Bezos API Mandate connect to the sentence you quoted?
passage ch03-029 <-- target section:
Principle 6: Build Loosely Coupled Systems
When the architecture of the system is designed to enable teams to test, deploy, and change systems without dependencies on other teams, teams require little communication to get work done. In other words, both the architecture and the teams are loosely coupled.

Google DevOps tech architecture guide10

In 2002, Bezos wrote an email to Amazon employees that became known as the Bezos API Mandate:11

All teams will henceforth expose their data and functionality through service interfaces.

Teams must communicate with each other through these interfaces.

There will be no other form of interprocess communication allowed: no direct linking, no direct reads of another team’s data store, no shared-memory model, no back-doors whatsoever. The only communication allowed is via service interface calls over the network.

It doesn’t matter what technology they use. HTTP, Corba, Pubsub, custom protocols—doesn’t matter.

All service interfaces, without exception, must be designed from the ground up to be externalizable. That is to say, the team must pla
answer: [Ch. 3] "Teams must communicate with each other through these interfaces."
This rule forces teams to use separate connections, which keeps the system parts loosely coupled.

## entity_relation-14  class=entity_relation  book=fde  section='Multicloud'
history:
User: What is multicloud disadvantages?
Book: [Ch. 4] "A multicloud methodology has several disadvantages."
Multicloud has downsides.
final question: How does Google Ads connect to the sentence you quoted?
passage ch04-036 <-- target section:
Multicloud
Multicloud simply refers to deploying workloads to multiple public clouds. Companies may have several motivations for multicloud deployments. SaaS platforms often wish to offer services close to existing customer cloud workloads. Snowflake and Databricks provide their SaaS offerings across multiple clouds for this reason. This is especially critical for data-intensive applications, where network latency and bandwidth limitations hamper performance, and data egress costs can be prohibitive.

Another common motivation for employing a multicloud approach is to take advantage of the best services across several clouds. For example, a company might want to handle its Google Ads and Analytics data on Google Cloud and deploy Kubernetes through GKE. And the company might also adopt Azure specifically for Microsoft workloads. Also, the company may like AWS because it has several best-in-class services (e.g., AWS Lambda) and enjoys huge mindshare, making it relatively easy to hire AWS-proficient engineers. Any mix of various cloud provider services is possible. Given the intense com
answer: [Ch. 4] "For example, a company might want to handle its Google Ads and Analytics data on Google Cloud and deploy Kubernetes through GKE."
Google Ads is an example of a service a company might choose to run on Google Cloud.

## entity_relation-15  class=entity_relation  book=fde  section='Total Cost of Ownership'
history:
User: what is total cost of ownership
Book: [Ch. 4] "Total cost of ownership (TCO) is the total estimated cost of an initiative, including the direct and indirect costs of products and services utilized."
TCO is the full price of a project, counting both direct bills and general overhead.
final question: How does ROI connect to the sentence you quoted?
passage ch04-011 <-- target section:
Total Cost of Ownership
This is capex, a significant capital outlay with a long-term plan to achieve a positive ROI on the effort and expense put forth.

Operational expenses, also known as opex, are the opposite of capex in certain respects. Opex is gradual and spread out over time. Whereas capex is long-term focused, opex is short-term. Opex can be pay-as-you-go or similar and allows a lot of flexibility. Opex is closer to a direct cost, making it easier to attribute to a data project.

Until recently, opex wasn’t an option for large data projects. Data systems often required multimillion-dollar contracts. This has changed with the advent of the cloud, as data platform services allow engineers to pay on a consumption-based model. In general, opex allows for a far greater ability for engineering teams to choose their software and hardware. Cloud-based services let data engineers iterate quickly with various software and technology configurations, often inexpensively.
answer: [Ch. 4] "This is capex, a significant capital outlay with a long-term plan to achieve a positive ROI on the effort and expense put forth."
ROI is the positive return you aim for after spending a large amount of money upfront.

## entity_relation-16  class=entity_relation  book=fde  section='Containers'
history:
User: What is containers?
Book: [Ch. 4] "Containers are often referred to as lightweight virtual machines."
Containers are small, fast software packages that run apps without needing a full operating system.
final question: How does Google App Engine connect to the sentence you quoted?
passage ch04-077 <-- target section:
Containers
For example, Hadoop now supports containers, allowing each job to have its own isolated dependencies.

Container clusters do not provide the same security and isolation that full VMs offer. Container escape—broadly, a class of exploits whereby code in a container gains privileges outside the container at the OS level—is common enough to be considered a risk for multitenancy. While Amazon EC2 is a truly multitenant environment with VMs from many customers hosted on the same hardware, a Kubernetes cluster should host code only within an environment of mutual trust (e.g., inside the walls of a single company). In addition, code review processes and vulnerability scanning are critical to ensure that a developer doesn’t introduce a security hole.

Various flavors of container platforms add additional serverless features. Containerized function platforms run containers as ephemeral units triggered by events rather than persistent services.12 This gives users the simplicity of AWS Lambda with the full flexibility of a container environment instead of the highly restrictive Lambda
answer: [Ch. 4] "And services such as AWS Fargate and Google App Engine run containers without managing a compute cluster required for Kubernetes."
Google App Engine lets you run containers without having to manage the underlying server cluster yourself.

## entity_relation-17  class=entity_relation  book=fde  section='Change Data Capture'
history:
User: what is change data capture
Book: [Ch. 7] "Change data capture (CDC), introduced in Chapter 2, is the process of ingesting changes from a source database system"
CDC in Chapter 2 captures changes from a database.
final question: How does Database Logs connect to the sentence you quoted?
passage ch05-013 <-- target section:
Change Data Capture
Change data capture (CDC) is a method for extracting each change event (insert, update, delete) that occurs in a database. CDC is frequently leveraged to replicate between databases in near real time or create an event stream for downstream processing.

CDC is handled differently depending on the database technology. Relational databases often generate an event log stored directly on the database server that can be processed to create a stream. (See “Database Logs”.) Many cloud NoSQL databases can send a log or event stream to a target storage location.
answer: [Ch. 5] "Relational databases often generate an event log stored directly on the database server that can be processed to create a stream."
Relational databases create a log file on the server that holds the changes.

## entity_relation-18  class=entity_relation  book=fde  section='Nonrelational databases: NoSQL'
history:
User: types of nosql databases
Book: [Ch. 5] "we consider the following database types: key-value, document, wide-column, graph, search, and time series."
These are the six main kinds of NoSQL databases listed in the text.
final question: How does SQL connect to the sentence you quoted?
passage ch05-032 <-- target section:
Nonrelational databases: NoSQL
While relational databases are terrific for many use cases, they’re not a one-size-fits-all solution. We often see that people start with a relational database under the impression it’s a universal appliance and shoehorn in a ton of use cases and workloads. As data and query requirements morph, the relational database collapses under its weight. At that point, you’ll want to use a database that’s appropriate for the specific workload under pressure. Enter nonrelational or NoSQL databases. NoSQL, which stands for not only SQL, refers to a whole class of databases that abandon the relational paradigm.

On the one hand, dropping relational constraints can improve performance, scalability, and schema flexibility. But as always in architecture, trade-offs exist. NoSQL databases also typically abandon various RDBMS characteristics, such as strong consistency, joins, or a fixed schema.

A big theme of this book is that data innovation is constant. Let’s take a quick look at the history of NoSQL, as it’s helpful to gain a perspective on why and how data innovat
answer: [Ch. 5] "NoSQL, which stands for not only SQL, refers to a whole class of databases that abandon the relational paradigm."
NoSQL means "not only SQL" and describes databases that do not use the relational model.
