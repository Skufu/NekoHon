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


## entity_relation-01  class=entity_relation  book=fde  section='Internal-Facing Versus External-Facing Data Engineers'
history:
User: What is internal facing vs external facing data engineering?
Book: [Ch. 1] "An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11)."
Internal-facing work helps the company's own people and processes.
final question: How does Internet relate to Internal-Facing Versus External-Facing Data Engineers?
passage ch01-046 <-- target section:
Internal-Facing Versus External-Facing Data Engineers
A data engineer serves several end users and faces many internal and external directions (Figure 1-9). Since not all data engineering workloads and responsibilities are the same, it’s essential to understand whom the data engineer serves. Depending on the end-use cases, a data engineer’s primary responsibilities are external facing, internal facing, or a blend of the two.

An external-facing data engineer typically aligns with the users of external-facing applications, such as social media apps, Internet of Things (IoT) devices, and ecommerce platforms. This data engineer architects, builds, and manages the systems that collect, store, and process transactional and event data from these applications. The systems built by these data engineers have a feedback loop from the application to the data pipeline, and then back to the application (Figure 1-10).
answer: [Ch. 1] "An external-facing data engineer typically aligns with the users of external-facing applications, such as social media apps, Internet of Things (IoT) devices, and ecommerce platforms."
External-facing engineers work on systems for apps and devices that connect to the internet.

## entity_relation-02  class=entity_relation  book=fde  section='Generation: Source Systems'
history:
User: What is source systems?
Book: [Ch. 2] "A source system is the origin of the data used in the data engineering lifecycle."
A source system is where the data starts.
final question: How does IoT relate to Generation: Source Systems?
passage ch02-006 <-- target section:
Generation: Source Systems
As an illustration, let’s look at two common source systems, one very traditional (an application database) and the other a more recent example (IoT swarms).

Figure 2-3 illustrates a traditional source system with several application servers supported by a database. This source system pattern became popular in the 1980s with the explosive success of relational database management systems (RDBMSs). The application + database pattern remains popular today with various modern evolutions of software development practices. For example, applications often consist of many small service/database pairs with microservices rather than a single monolith.

Let’s look at another example of a source system. Figure 2-4 illustrates an IoT swarm: a fleet of devices (circles) sends data messages (rectangles) to a central collection system. This IoT source system is increasingly common as IoT devices such as sensors, smart devices, and much more increase in the wild.
answer: [Ch. 2] "Figure 2-4 illustrates an IoT swarm: a fleet of devices (circles) sends data messages (rectangles) to a central collection system."
IoT acts as a source system where many devices send data to a central place.

## entity_relation-03  class=entity_relation  book=fde  section='What Is Data Ingestion?'
history:
User: what is data ingestion
Book: [Ch. 7] "Data ingestion is the process of moving data from one place to another."
It means taking data from where it starts and moving it to where it is stored.
final question: How does ETL relate to What Is Data Ingestion?
passage ch07-003 <-- target section:
What Is Data Ingestion?
We consider this another part of the general data transformation process covered in Chapter 8. Data Pipelines Defined

Data pipelines begin in source systems, but ingestion is the stage where data engineers begin actively designing data pipeline activities. In the data engineering space, a good deal of ceremony occurs around data movement and processing patterns, with established patterns such as ETL, newer patterns such as ELT, and new names for long-established practices (reverse ETL) and data sharing.

All of these concepts are encompassed in the idea of a data pipeline. It is essential to understand the details of these various patterns and know that a modern data pipeline includes all of them. As the world moves away from a traditional monolithic approach with rigid constraints on data movement, and toward an open ecosystem of cloud services that are assembled like LEGO bricks to realize products, data engineers prioritize using the right tools to accomplish the desired outcome over adhering to a narrow philosophy of data movement.

In general, here’s our
answer: [Ch. 7] "In the data engineering space, a good deal of ceremony occurs around data movement and processing patterns, with established patterns such as ETL, newer patterns such as ELT, and new names for long-established practices (reverse ETL) and data sharing."
ETL is one of the standard methods used to move and process data within a pipeline.

## entity_relation-04  class=entity_relation  book=fde  section='Data Management'
history:
User: what is data management
Book: [Ch. 2] "Data management is the development, execution, and supervision of plans, policies, programs, and practices that deliver, control, protect, and enhance the value of data and information assets throughout their lifecycle."
Data management encompasses practices to keep data secure, reliable, and accessible throughout its lifecycle.
final question: How does C-suite relate to Data Management?
passage ch02-047 <-- target section:
Data Management
That’s a bit lengthy, so let’s look at how it ties to data engineering. Data engineers manage the data lifecycle, and data management encompasses the set of best practices that data engineers will use to accomplish this task, both technically and strategically. Without a framework for managing data, data engineers are simply technicians operating in a vacuum. Data engineers need a broader perspective of data’s utility across the organization, from the source systems to the C-suite, and everywhere in between.

Why is data management important? Data management demonstrates that data is vital to daily operations, just as businesses view financial resources, finished goods, or real estate as assets. Data management practices form a cohesive framework that everyone can adopt to ensure that the organization gets value from data and handles it appropriately.

Data management has quite a few facets, including the following:

Data governance, including discoverability and accountability

Data modeling and design

Data lineage

Storage and operations

Data integration and inter
answer: [Ch. 2] "Data engineers need a broader perspective of data’s utility across the organization, from the source systems to the C-suite, and everywhere in between."
Data engineers must understand how data is useful for everyone, including top executives.

## entity_relation-05  class=entity_relation  book=fde  section='Orchestration'
history:
User: what is orchestration in the data engineering lifecycle
Book: [Ch. 2] "Orchestration is the process of coordinating many jobs to run as quickly and efficiently as possible on a scheduled cadence."
Orchestration coordinates when and how automated data workflows execute across systems.
final question: How does Apache Airflow relate to Orchestration in engineering?
passage ch02-079 <-- target section:
Orchestration
We think that orchestration matters because we view it as really the center of gravity of both the data platform as well as the data lifecycle, the software development lifecycle as it comes to data.
 
 Nick Schrock, founder of Elementl9

Orchestration is not only a central DataOps process, but also a critical part of the engineering and deployment flow for data jobs. So, what is orchestration?

Orchestration is the process of coordinating many jobs to run as quickly and efficiently as possible on a scheduled cadence. For instance, people often refer to orchestration tools like Apache Airflow as schedulers. This isn’t quite accurate. A pure scheduler, such as cron, is aware only of time; an orchestration engine builds in metadata on job dependencies, generally in the form of a directed acyclic graph (DAG). The DAG can be run once or scheduled to run at a fixed interval of daily, weekly, every hour, every five minutes, etc.
answer: [Ch. 2] "people often refer to orchestration tools like Apache Airflow as schedulers."
Apache Airflow is a tool used for orchestration, though it is more than just a scheduler.

## entity_relation-06  class=entity_relation  book=fde  section='Metadata'
history:
User: types of metadata
Book: [Ch. 2] "Metadata is data about data"
Metadata describes information.
final question: How does Schema relate to Metadata in types?
passage ch02-053 <-- target section:
Metadata
Business metadata relates to the way data is used in the business, including business and data definitions, data rules and logic, how and where data is used, and the data owner(s).

A data engineer uses business metadata to answer nontechnical questions about who, what, where, and how. For example, a data engineer may be tasked with creating a data pipeline for customer sales analysis. But what is a customer? Is it someone who’s purchased in the last 90 days? Or someone who’s purchased at any time the business has been open? A data engineer would use the correct data to refer to business metadata (data dictionary or data catalog) to look up how a “customer” is defined. Business metadata provides a data engineer with the right context and definitions to properly use data.

Technical metadata describes the data created and used by systems across the data engineering lifecycle. It includes the data model and schema, data lineage, field mappings, and pipeline workflows. A data engineer uses technical metadata to create, connect, and monitor various systems across the data engine
answer: [Ch. 2] "Technical metadata describes the data created and used by systems across the data engineering lifecycle. It includes the data model and schema, data lineage, field mappings, and pipeline workflows."
Schema is a specific type of technical metadata.

## entity_relation-07  class=entity_relation  book=fde  section='Data quality'
history:
User: what is data quality
Book: [Ch. 2] "Data quality is the optimization of data toward the desired state and orbits the question, “What do you get compared with what you expect?”"
Data quality means making sure your data matches what you planned to get.
final question: How does Google relate to Data quality?
passage ch02-058 <-- target section:
Data quality
Any bot-generated events misclassified as human present data accuracy issues, and vice versa.

A variety of interesting problems arise concerning completeness and timeliness. In the Google paper introducing the Dataflow model, the authors give the example of an offline video platform that displays ads.5 The platform downloads video and ads while a connection is present, allows the user to watch these while offline, and then uploads ad view data once a connection is present again. This data may arrive late, well after the ads are watched. How does the platform handle billing for the ads?

Fundamentally, this problem can’t be solved by purely technical means. Rather, engineers will need to determine their standards for late-arriving data and enforce these uniformly, possibly with the help of various technology tools.

Master Data Management

Master data is data about business entities such as employees, customers, products, and locations. As organizations grow larger and more complex through organic growth and acquisitions, and collaborate with other businesses, maintainin
answer: [Ch. 2] "In the Google paper introducing the Dataflow model, the authors give the example of an offline video platform that displays ads."
Google's paper uses an offline video example to show how late data affects quality.

## entity_relation-08  class=entity_relation  book=fde  section='What Is the Data Engineering Lifecycle?'
history:
User: what are the undercurrents of the data engineering lifecycle
Book: [Ch. 2] "Data engineering is rapidly maturing. Whereas prior cycles of data engineering simply focused on the technology layer, the continued abstraction and simplification of tools and practices have shifted this focus. Data engineering now encompasses far more than tools and technology. The field is now moving up the value chain, incorporating traditional enterprise practices such as data manage
final question: How does Ingestion relate to What Is the Data Engineering Lifecycle?
passage ch02-002 <-- target section:
What Is the Data Engineering Lifecycle?
The data engineering lifecycle comprises stages that turn raw data ingredients into a useful end product, ready for consumption by analysts, data scientists, ML engineers, and others. This chapter introduces the major stages of the data engineering lifecycle, focusing on each stage’s core concepts and saving details for later chapters.

We divide the data engineering lifecycle into five stages (Figure 2-1, top):

Generation

Storage

Ingestion

Transformation

Serving data

We begin the data engineering lifecycle by getting data from source systems and storing it. Next, we transform the data and then proceed to our central goal, serving data to analysts, data scientists, ML engineers, and others. In reality, storage occurs throughout the lifecycle as data flows from beginning to end—hence, the diagram shows the storage “stage” as a foundation that underpins other stages.

In general, the middle stages—storage, ingestion, transformation—can get a bit jumbled. And that’s OK. Although we split out the distinct parts of the data engineering lifecyc
answer: [Ch. 2] "We divide the data engineering lifecycle into five stages (Figure 2-1, top):"
Ingestion is one of the five main steps in the data engineering process.

## entity_relation-09  class=entity_relation  book=fde  section='Additional Resources'
history:
User: togaf defines data architecture as what
Book: [Ch. 3] "A description of the structure and interaction of the enterprise’s major types and sources of data, logical data assets, physical data assets, and data management resources."
TOGAF says data architecture explains how an organization's data is organized and how different data parts work together.
final question: How does Test Data Quality relate to Additional Resources in architecture?
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
It is listed as a recommended reading under the Additional Resources section.

## entity_relation-10  class=entity_relation  book=fde  section='Principle 9: Embrace FinOps'
history:
User: what does finops help a data team do
Book: [Ch. 3] "FinOps is an evolving cloud financial management discipline and cultural practice that enables organizations to get maximum business value by helping engineering, finance, technology, and business teams to collaborate on data-driven spending decisions."
FinOps helps teams work together to make smart spending choices for better business results.
final question: How does FinOps Foundation relate to Principle 9: Embrace FinOps in data?
passage ch03-039 <-- target section:
Principle 9: Embrace FinOps
Let’s start by considering a couple of definitions of FinOps. First, the FinOps Foundation offers this:16

FinOps is an evolving cloud financial management discipline and cultural practice that enables organizations to get maximum business value by helping engineering, finance, technology, and business teams to collaborate on data-driven spending decisions.

In addition, J. R. Sorment and Mike Fuller provide the following definition in Cloud FinOps:17

The term “FinOps” typically refers to the emerging professional movement that advocates a collaborative working relationship between DevOps and Finance, resulting in an iterative, data-driven management of infrastructure spending (i.e., lowering the unit economics of cloud) while simultaneously increasing the cost efficiency and, ultimately, the profitability of the cloud environment.
answer: [Ch. 3] "First, the FinOps Foundation offers this:16"
The FinOps Foundation provides the definition for FinOps.
