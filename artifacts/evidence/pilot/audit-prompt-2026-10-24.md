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

## entity_relation-11  class=entity_relation  book=fde  section='Principle 6: Build Loosely Coupled Systems'
history:
User: What is loosely coupled systems?
Book: [Ch. 3] "Systems are broken into many small components"
Systems are divided into small parts.
final question: How does Bezos API Mandate relate to Principle 6: Build Loosely Coupled Systems?
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
answer: [Ch. 3] "All teams will henceforth expose their data and functionality through service interfaces."
Teams must use specific service connections to talk to each other instead of direct links.

## entity_relation-12  class=entity_relation  book=fde  section='Total Cost of Ownership'
history:
User: what is total cost of ownership
Book: [Ch. 4] "Total cost of ownership (TCO) is the total estimated cost of an initiative, including the direct and indirect costs of products and services utilized."
TCO is the full price of a project, counting both direct bills and general overhead.
final question: How does ROI relate to Total Cost of Ownership?
passage ch04-011 <-- target section:
Total Cost of Ownership
This is capex, a significant capital outlay with a long-term plan to achieve a positive ROI on the effort and expense put forth.

Operational expenses, also known as opex, are the opposite of capex in certain respects. Opex is gradual and spread out over time. Whereas capex is long-term focused, opex is short-term. Opex can be pay-as-you-go or similar and allows a lot of flexibility. Opex is closer to a direct cost, making it easier to attribute to a data project.

Until recently, opex wasn’t an option for large data projects. Data systems often required multimillion-dollar contracts. This has changed with the advent of the cloud, as data platform services allow engineers to pay on a consumption-based model. In general, opex allows for a far greater ability for engineering teams to choose their software and hardware. Cloud-based services let data engineers iterate quickly with various software and technology configurations, often inexpensively.
answer: [Ch. 4] "This is capex, a significant capital outlay with a long-term plan to achieve a positive ROI on the effort and expense put forth."
Big upfront spending is done with the goal of making a profit later.

## entity_relation-13  class=entity_relation  book=fde  section='Change Data Capture'
history:
User: what is change data capture
Book: [Ch. 7] "Change data capture (CDC), introduced in Chapter 2, is the process of ingesting changes from a source database system"
CDC in Chapter 2 captures changes from a database.
final question: How does Database Logs relate to Change Data Capture?
passage ch05-013 <-- target section:
Change Data Capture
Change data capture (CDC) is a method for extracting each change event (insert, update, delete) that occurs in a database. CDC is frequently leveraged to replicate between databases in near real time or create an event stream for downstream processing.

CDC is handled differently depending on the database technology. Relational databases often generate an event log stored directly on the database server that can be processed to create a stream. (See “Database Logs”.) Many cloud NoSQL databases can send a log or event stream to a target storage location.
answer: [Ch. 5] "Relational databases often generate an event log stored directly on the database server that can be processed to create a stream."
CDC uses the database's event log to track changes.

## entity_relation-14  class=entity_relation  book=fde  section='Nonrelational databases: NoSQL'
history:
User: types of nosql databases
Book: [Ch. 5] "we consider the following database types: key-value, document, wide-column, graph, search, and time series."
These are the six main kinds of NoSQL databases listed in the text.
final question: How does SQL relate to Nonrelational databases: NoSQL?
passage ch05-032 <-- target section:
Nonrelational databases: NoSQL
While relational databases are terrific for many use cases, they’re not a one-size-fits-all solution. We often see that people start with a relational database under the impression it’s a universal appliance and shoehorn in a ton of use cases and workloads. As data and query requirements morph, the relational database collapses under its weight. At that point, you’ll want to use a database that’s appropriate for the specific workload under pressure. Enter nonrelational or NoSQL databases. NoSQL, which stands for not only SQL, refers to a whole class of databases that abandon the relational paradigm.

On the one hand, dropping relational constraints can improve performance, scalability, and schema flexibility. But as always in architecture, trade-offs exist. NoSQL databases also typically abandon various RDBMS characteristics, such as strong consistency, joins, or a fixed schema.

A big theme of this book is that data innovation is constant. Let’s take a quick look at the history of NoSQL, as it’s helpful to gain a perspective on why and how data innovat
answer: [Ch. 5] "NoSQL, which stands for not only SQL, refers to a whole class of databases that abandon the relational paradigm."
NoSQL means "not only SQL" and describes databases that do not use the relational model.

## entity_relation-15  class=entity_relation  book=fde  section='Insert-Only'
history:
User: What is advantages of insert-only tables?
Book: [Ch. 5] "In a sense, the insert-only pattern maintains a database log directly in the table itself, making it especially useful if the application needs access to history."
It keeps a full record of past changes so you can see how data changed over time.
final question: How does Record ID relate to Insert-Only?
passage ch05-020 <-- target section:
Insert-Only
The insert-only pattern retains history directly in a table containing data. Rather than updating records, new records get inserted with a timestamp indicating when they were created (Table 5-1). For example, suppose you have a table of customer addresses. Following a CRUD pattern, you would simply update the record if the customer changed their address. With the insert-only pattern, a new address record is inserted with the same customer ID. To read the current customer address by customer ID, you would look up the latest record under that ID.

Table 5-1. An insert-only pattern produces multiple versions of a record
 
 
 Record ID
 Value
 Timestamp
 
 
 
 
 1
 40
 2021-09-19T00:10:23+00:00
 
 
 1
 51
 2021-09-30T00:12:00+00:00

In a sense, the insert-only pattern maintains a database log directly in the table itself, making it especially useful if the application needs access to history. For example, the insert-only pattern would work well for a banking application designed to present customer address history.

A separate analytics insert-only pattern is
answer: [Ch. 5] "With the insert-only pattern, a new address record is inserted with the same customer ID."
The Record ID stays the same for different versions of the same item.

## entity_relation-16  class=entity_relation  book=fde  section='Data Sharing'
history:
User: what is data sharing between organizations
Book: [Ch. 6] "Data sharing allows organizations and individuals to share specific data and carefully defined permissions with specific entities. Data sharing allows data scientists to share data from a sandbox with their collaborators within an organization. Across organizations, data sharing facilitates collaboration between partner businesses. For example, an ad tech company can share advertising dat
final question: How does Snowflake relate to Data Sharing?
passage ch09-046 <-- target section:
Data Sharing
Chapter 5 includes an extensive discussion of data sharing. Any data exchange between organizations or units within a larger organization can be viewed as data sharing. Still, we mean specifically sharing through massively multitenant storage systems in a cloud environment. Data sharing generally turns data serving into a security and access control problem.

The actual queries are now handled by the data consumers (analysts and data scientists) rather than the engineers sourcing the data. Whether serving data in a data mesh within an organization, providing data to the public, or serving to partner businesses, data sharing is a compelling serving model. Data sharing is increasingly a core feature of major data platforms like Snowflake, Redshift, and BigQuery allowing companies to share data safely and securely with each other.
answer: [Ch. 9] "Data sharing is increasingly a core feature of major data platforms like Snowflake, Redshift, and BigQuery allowing companies to share data safely and securely with each other."
Snowflake is a platform that has data sharing as a main feature.

## entity_relation-17  class=entity_relation  book=fde  section='Object stores for data engineering applications'
history:
User: what is object storage
Book: [Ch. 6] "Object storage contains objects of all shapes and sizes (Figure 6-8)"
Objects in object storage can be any type of file or data.
final question: How does Apache Hudi relate to Object stores for data engineering applications in storage?
passage ch06-045 <-- target section:
Object stores for data engineering applications
From the standpoint of data engineering, object stores provide excellent performance for large batch reads and batch writes. This corresponds well to the use case for massive OLAP systems. A bit of data engineering folklore says that object stores are not good for updates, but this is only partially true. Object stores are an inferior fit for transactional workloads with many small updates every second; these use cases are much better served by transactional databases or block storage systems. Object stores work well for a low rate of update operations, where each operation updates a large volume of data.

Object stores are now the gold standard of storage for data lakes. In the early days of data lakes, write once, read many (WORM) was the operational standard, but this had more to do with the complexities of managing data versions and files than the limitations of HDFS and object stores. Since then, systems such as Apache Hudi and Delta Lake have emerged to manage this complexity, and privacy regulations such as GDPR and CCPA have mad
answer: [Ch. 6] "Since then, systems such as Apache Hudi and Delta Lake have emerged to manage this complexity, and privacy regulations such as GDPR and CCPA have made deletion and update capabilities imperative."
Apache Hudi helps manage the difficulty of updating and deleting data in object stores.

## entity_relation-18  class=entity_relation  book=fde  section='The Data Lakehouse'
history:
User: what is a data lakehouse
Book: [Ch. 6] "The data lakehouse is an architecture that combines aspects of the data warehouse and the data lake."
A data lakehouse blends the structured reliability of warehouses with the cheap scale of object storage.
final question: How does Delta Lake relate to The Data Lakehouse?
passage ch06-076 <-- target section:
The Data Lakehouse
The complexities of managing underlying files and storage are fully hidden from the user.

The key advantage of the data lakehouse over proprietary tools is interoperability. It’s much easier to exchange data between tools when stored in an open file format. Reserializing data from a proprietary database format incurs overhead in processing, time, and cost. In a data lakehouse architecture, various tools can connect to the metadata layer and read data directly from object storage.

It is important to emphasize that much of the data in a data lakehouse may not have a table structure imposed. We can impose data warehouse features where we need them in a lakehouse, leaving other data in a raw or even unstructured format.

The data lakehouse technology is evolving rapidly. A variety of new competitors to Delta Lake have emerged, including Apache Hudi and Apache Iceberg. See Appendix A for more details.
answer: [Ch. 6] "A variety of new competitors to Delta Lake have emerged, including Apache Hudi and Apache Iceberg."
Delta Lake is one of several competing technologies for building data lakehouses.

## premise_trap-19  class=premise_trap  book=fde  section='The Data Lifecycle Versus the Data Engineering Lifecycle'
history:
User: What is data engineering lifecycle?
Book: [Ch. 2] "The data engineering lifecycle comprises stages that turn raw data ingredients into a useful end product, ready for consumption by analysts, data scientists, ML engineers, and others."
The data engineering lifecycle transforms raw data into a useful end product ready for consumption.
final question: What did Dr. Helena Voss say about Data Lifecycle in 1998?
passage ch02-004 <-- target section:
The Data Lifecycle Versus the Data Engineering Lifecycle
You may be wondering about the difference between the overall data lifecycle and the data engineering lifecycle. There’s a subtle distinction between the two. The data engineering lifecycle is a subset of the whole data lifecycle (Figure 2-2). Whereas the full data lifecycle encompasses data across its entire lifespan, the data engineering lifecycle focuses on the stages a data engineer controls.
passage ch02-002:
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
passage ch01-006:
The Data Engineering Lifecycle
It is all too easy to fixate on technology and miss the bigger picture myopically. This book centers around a big idea called the data engineering lifecycle (Figure 1-1), which we believe gives data engineers the holistic context to view their role.

The data engineering lifecycle shifts the conversation away from technology and toward the data itself and the end goals that it must serve. The stages of the data engineering lifecycle are as follows:

Generation

Storage

Ingestion

Transformation

Serving

The data engineering lifecycle also has a notion of undercurrents—critical ideas across the entire lifecycle. These include security, data management, DataOps, data architecture, orchestration, and software engineering. We cover the data engineering lifecycle and its undercurrents more extensively in Chapter 2. Still, we introduce it here because it is essential to our definition of data engineering and the discussion that follows in this chapter.

Now that you have a working definition of data engineering and an introduction to its lifecycle, let’s ta
answer: Not in this book.
expected: Not in this book.

## premise_trap-20  class=premise_trap  book=fde  section='Data Engineering Defined'
history:
User: what is data engineering
Book: [Ch. 1] "Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning."
Data engineering builds systems that turn raw data into clean, usable information for analysis.
final question: What did Marcus Feld say about Data Engineering in 2001?
passage ch01-005 <-- target section:
Data Engineering Defined
When we unpack the common threads of how various people define data engineering, an obvious pattern emerges: a data engineer gets data, stores it, and prepares it for consumption by data scientists, analysts, and others. We define data engineering and data engineer as follows:

Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning. Data engineering is the intersection of security, data management, DataOps, data architecture, orchestration, and software engineering. A data engineer manages the data engineering lifecycle, beginning with getting data from source systems and ending with serving data for use cases, such as analysis or machine learning.
passage ch01-001:
Chapter 1. Data Engineering Described
If you work in data or software, you may have noticed data engineering emerging from the shadows and now sharing the stage with data science. Data engineering is one of the hottest fields in data and technology, and for a good reason. It builds the foundation for data science and analytics in production. This chapter explores what data engineering is, how the field was born and its evolution, the skills of data engineers, and with whom they work.
passage ch01-004:
What Is Data Engineering?
Maxime Beauchemin4

Data engineering is all about the movement, manipulation, and management of data. Lewis Gavin5

Wow! It’s entirely understandable if you’ve been confused about data engineering. That’s only a handful of definitions, and they contain an enormous range of opinions about the meaning of data engineering.
answer: Not in this book.
expected: Not in this book.

## premise_trap-21  class=premise_trap  book=fde  section='Data Engineering and Data Science'
history:
User: what does a data engineer actually do
Book: [Ch. 1] "Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning."
Data engineers build and keep running the systems that turn raw data into clean, usable information for other teams.
final question: What did Priya Raman say about Data Engineering in 2007?
passage ch01-022 <-- target section:
Data Engineering and Data Science
Rogati argues that companies need to build a solid data foundation (the bottom three levels of the hierarchy) before tackling areas such as AI and ML.

Data scientists aren’t typically trained to engineer production-grade data systems, and they end up doing this work haphazardly because they lack the support and resources of a data engineer. In an ideal world, data scientists should spend more than 90% of their time focused on the top layers of the pyramid: analytics, experimentation, and ML. When data engineers focus on these bottom parts of the hierarchy, they build a solid foundation for data scientists to succeed.

With data science driving advanced analytics and ML, data engineering straddles the divide between getting data and getting value from data (see Figure 1-6). We believe data engineering is of equal importance and visibility to data science, with data engineers playing a vital role in making data science successful in production.
passage ch01-024:
Data Engineering Skills and Activities
Their work would be devoted to cluster administration and maintenance, managing overhead, and writing pipeline and transformation jobs, among other tasks.

Nowadays, the data-tooling landscape is dramatically less complicated to manage and deploy. Modern data tools considerably abstract and simplify workflows. As a result, data engineers are now focused on balancing the simplest and most cost-effective, best-of-breed services that deliver value to the business. The data engineer is also expected to create agile data architectures that evolve as new trends emerge.

What are some things a data engineer does not do? A data engineer typically does not directly build ML models, create reports or dashboards, perform data analysis, build key performance indicators (KPIs), or develop software applications. A data engineer should have a good functioning understanding of these areas to serve stakeholders best.
passage ch01-005:
Data Engineering Defined
When we unpack the common threads of how various people define data engineering, an obvious pattern emerges: a data engineer gets data, stores it, and prepares it for consumption by data scientists, analysts, and others. We define data engineering and data engineer as follows:

Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning. Data engineering is the intersection of security, data management, DataOps, data architecture, orchestration, and software engineering. A data engineer manages the data engineering lifecycle, beginning with getting data from source systems and ending with serving data for use cases, such as analysis or machine learning.
answer: Not in this book.
expected: Not in this book.

## premise_trap-22  class=premise_trap  book=fde  section='Data Engineering and Data Science'
history:
User: What is data science vs data engineering?
Book: [Ch. 1] "We believe data engineering is separate from data science and analytics."
Data engineering and data science are different jobs that work together.
final question: What did Tomas Lindgren say about Data Engineering in 2012?
passage ch01-021 <-- target section:
Data Engineering and Data Science
Where does data engineering fit in with data science? There’s some debate, with some arguing data engineering is a subdiscipline of data science. We believe data engineering is separate from data science and analytics. They complement each other, but they are distinctly different. Data engineering sits upstream from data science (Figure 1-4), meaning data engineers provide the inputs used by data scientists (downstream from data engineering), who convert these inputs into something useful.

Consider the Data Science Hierarchy of Needs (Figure 1-5). In 2017, Monica Rogati published this hierarchy in an article that showed where AI and machine learning (ML) sat in proximity to more “mundane” areas such as data movement/storage, collection, and infrastructure.

Although many data scientists are eager to build and tune ML models, the reality is an estimated 70% to 80% of their time is spent toiling in the bottom three parts of the hierarchy—gathering data, cleaning data, processing data—and only a tiny slice of their time on analysis and ML. Rogati argue
passage ch11-013:
Titles and Responsibilities Will Morph...
While the data engineering lifecycle isn’t going anywhere anytime soon, the boundaries between software engineering, data engineering, data science, and ML engineering are increasingly fuzzy. In fact, like the authors, many data scientists are transformed into data engineers through an organic process; tasked with doing “data science” but lacking the tools to do their jobs, they take on the job of designing and building systems to serve the data engineering lifecycle.

As simplicity moves up the stack, data scientists will spend a smaller slice of their time gathering and munging data. But this trend will extend beyond data scientists. Simplification also means data engineers will spend less time on low-level tasks in the data engineering lifecycle (managing servers, configuration, etc.), and “enterprisey” data engineering will become more prevalent.

As data becomes more tightly embedded in every business’s processes, new roles will emerge in the realm of data and algorithms. One possibility is a role that sits between ML engineering and dat
passage ch01-001:
Chapter 1. Data Engineering Described
If you work in data or software, you may have noticed data engineering emerging from the shadows and now sharing the stage with data science. Data engineering is one of the hottest fields in data and technology, and for a good reason. It builds the foundation for data science and analytics in production. This chapter explores what data engineering is, how the field was born and its evolution, the skills of data engineers, and with whom they work.
answer: Not in this book.
expected: Not in this book.

## premise_trap-23  class=premise_trap  book=fde  section='Internal-Facing Versus External-Facing Data Engineers'
history:
User: What is internal facing vs external facing data engineering?
Book: [Ch. 1] "An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11)."
Internal-facing work helps the company's own people and processes.
final question: What did Dr. Helena Voss say about Internal-Facing in 1998?
passage ch01-047 <-- target section:
Internal-Facing Versus External-Facing Data Engineers
The systems built by these data engineers have a feedback loop from the application to the data pipeline, and then back to the application (Figure 1-10).

External-facing data engineering comes with a unique set of problems. External-facing query engines often handle much larger concurrency loads than internal-facing systems. Engineers also need to consider putting tight limits on queries that users can run to limit the infrastructure impact of any single user. In addition, security is a much more complex and sensitive problem for external queries, especially if the data being queried is multitenant (data from many customers and housed in a single table).

An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11). Examples include creating and maintaining data pipelines and data warehouses for BI dashboards, reports, business processes, data science, and ML models.

External-facing and internal-facing responsibilities are often blended. In practice
passage ch01-046:
Internal-Facing Versus External-Facing Data Engineers
A data engineer serves several end users and faces many internal and external directions (Figure 1-9). Since not all data engineering workloads and responsibilities are the same, it’s essential to understand whom the data engineer serves. Depending on the end-use cases, a data engineer’s primary responsibilities are external facing, internal facing, or a blend of the two.

An external-facing data engineer typically aligns with the users of external-facing applications, such as social media apps, Internet of Things (IoT) devices, and ecommerce platforms. This data engineer architects, builds, and manages the systems that collect, store, and process transactional and event data from these applications. The systems built by these data engineers have a feedback loop from the application to the data pipeline, and then back to the application (Figure 1-10).
passage ch09-009:
Data Products
Rinse and repeat. When building a data product, keep these considerations in mind:

When someone uses the data product, what do they hope to accomplish? All too often, data products are made without a clear understanding of the outcome expected by the user.

Will the data product serve internal or external users? In Chapter 2, we discussed internal- and external-facing data engineering. When creating a data product, knowing whether your customer is internal or external facing will impact the way data is served.

What are the outcomes and ROI of the data product you’re building?

Building data products that people will use and love is critical. Nothing will ruin the adoption of a data product more than unwanted utility and loss of trust in the data outputs. Pay attention to the adoption and usage of data products, and be willing to adjust to make users happy.
answer: Not in this book.
expected: Not in this book.

## premise_trap-24  class=premise_trap  book=fde  section='Data Maturity and the Data Engineer'
history:
User: what is data maturity
Book: [Ch. 1] "Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company."
Data maturity measures how effectively an organization utilizes data to drive operations and strategic decisions.
final question: What did Marcus Feld say about Data Maturity in 2001?
passage ch01-025 <-- target section:
Data Maturity and the Data Engineer
The level of data engineering complexity within a company depends a great deal on the company’s data maturity. This significantly impacts a data engineer’s day-to-day job responsibilities and career progression. What is data maturity, exactly?

Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company. An early-stage startup can have greater data maturity than a 100-year-old company with annual revenues in the billions. What matters is the way data is leveraged as a competitive advantage.

Data maturity models have many versions, such as Data Management Maturity (DMM) and others, and it’s hard to pick one that is both simple and useful for data engineering. So, we’ll create our own simplified data maturity model. Our data maturity model (Figure 1-8) has three stages: starting with data, scaling with data, and leading with data. Let’s look at each of these stages and at what a data engineer typically does at each 
passage ch03-084:
Modern Data Stack
The modern data stack (Figure 3-13) is currently a trendy analytics architecture that highlights the type of abstraction we expect to see more widely used over the next several years. Whereas past data stacks relied on expensive, monolithic toolsets, the main objective of the modern data stack is to use cloud-based, plug-and-play, easy-to-use, off-the-shelf components to create a modular and cost-effective data architecture. These components include data pipelines, storage, transformation, data management/governance, monitoring, visualization, and exploration. The domain is still in flux, and the specific tools are changing and evolving rapidly, but the core aim will remain the same: to reduce complexity and increase modularization. Note that the notion of a modern data stack integrates nicely with the converged data platform idea from the previous section.
passage ch01-043:
The Continuum of Data Engineering Roles, from A to B
Although job descriptions paint a data engineer as a “unicorn” who must possess every data skill imaginable, data engineers don’t all do the same type of work or have the same skill set. Data maturity is a helpful guide to understanding the types of data challenges a company will face as it grows its data capability. It’s beneficial to look at some critical distinctions in the kinds of work data engineers do. Though these distinctions are simplistic, they clarify what data scientists and data engineers do and avoid lumping either role into the unicorn bucket.

In data science, there’s the notion of type A and type B data scientists.10 Type A data scientists—where A stands for analysis—focus on understanding and deriving insight from data. Type B data scientists—where B stands for building—share similar backgrounds as type A data scientists and possess strong programming skills. The type B data scientist builds systems that make data science work in production. Borrowing from this data scientist continuum, we’ll create a similar dis
answer: Not in this book.
expected: Not in this book.

## premise_trap-25  class=premise_trap  book=fde  section='The Data Lifecycle Versus the Data Engineering Lifecycle'
history:
User: what is the data engineering lifecycle
Book: [Ch. 2] "The data engineering lifecycle comprises stages that turn raw data ingredients into a useful end product, ready for consumption by analysts, data scientists, ML engineers, and others."
The data engineering lifecycle transforms raw data into a useful end product ready for consumption.
final question: What did Priya Raman say about Data Lifecycle in 2007?
passage ch02-004 <-- target section:
The Data Lifecycle Versus the Data Engineering Lifecycle
You may be wondering about the difference between the overall data lifecycle and the data engineering lifecycle. There’s a subtle distinction between the two. The data engineering lifecycle is a subset of the whole data lifecycle (Figure 2-2). Whereas the full data lifecycle encompasses data across its entire lifespan, the data engineering lifecycle focuses on the stages a data engineer controls.
passage ch02-002:
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
passage ch01-006:
The Data Engineering Lifecycle
It is all too easy to fixate on technology and miss the bigger picture myopically. This book centers around a big idea called the data engineering lifecycle (Figure 1-1), which we believe gives data engineers the holistic context to view their role.

The data engineering lifecycle shifts the conversation away from technology and toward the data itself and the end goals that it must serve. The stages of the data engineering lifecycle are as follows:

Generation

Storage

Ingestion

Transformation

Serving

The data engineering lifecycle also has a notion of undercurrents—critical ideas across the entire lifecycle. These include security, data management, DataOps, data architecture, orchestration, and software engineering. We cover the data engineering lifecycle and its undercurrents more extensively in Chapter 2. Still, we introduce it here because it is essential to our definition of data engineering and the discussion that follows in this chapter.

Now that you have a working definition of data engineering and an introduction to its lifecycle, let’s ta
answer: Not in this book.
expected: Not in this book.

## premise_trap-26  class=premise_trap  book=fde  section='Generation: Source Systems'
history:
User: What is source systems?
Book: [Ch. 2] "A source system is the origin of the data used in the data engineering lifecycle."
A source system is where the data starts.
final question: What did Tomas Lindgren say about Generation in 2012?
passage ch02-005 <-- target section:
Generation: Source Systems
A source system is the origin of the data used in the data engineering lifecycle. For example, a source system could be an IoT device, an application message queue, or a transactional database. A data engineer consumes data from a source system but doesn’t typically own or control the source system itself. The data engineer needs to have a working understanding of the way source systems work, the way they generate data, the frequency and velocity of the data, and the variety of data they generate.

Engineers also need to keep an open line of communication with source system owners on changes that could break pipelines and analytics. Application code might change the structure of data in a field, or the application team might even choose to migrate the backend to an entirely new database technology.

A major challenge in data engineering is the dizzying array of data source systems engineers must work with and understand. As an illustration, let’s look at two common source systems, one very traditional (an application database) and the other a more recent ex
passage ch05-004:
Source Systems: Main Ideas
Source systems produce data in various ways. This section discusses the main ideas you’ll frequently encounter as you work with source systems.
passage ch02-006:
Generation: Source Systems
As an illustration, let’s look at two common source systems, one very traditional (an application database) and the other a more recent example (IoT swarms).

Figure 2-3 illustrates a traditional source system with several application servers supported by a database. This source system pattern became popular in the 1980s with the explosive success of relational database management systems (RDBMSs). The application + database pattern remains popular today with various modern evolutions of software development practices. For example, applications often consist of many small service/database pairs with microservices rather than a single monolith.

Let’s look at another example of a source system. Figure 2-4 illustrates an IoT swarm: a fleet of devices (circles) sends data messages (rectangles) to a central collection system. This IoT source system is increasingly common as IoT devices such as sensors, smart devices, and much more increase in the wild.
answer: Not in this book.
expected: Not in this book.

## premise_trap-27  class=premise_trap  book=fde  section='What Is Data Ingestion?'
history:
User: what is data ingestion
Book: [Ch. 7] "Data ingestion is the process of moving data from one place to another."
It means taking data from where it starts and moving it to where it is stored.
final question: What did Dr. Helena Voss say about Data Ingestion in 1998?
passage ch07-002 <-- target section:
What Is Data Ingestion?
Data ingestion is the process of moving data from one place to another. Data ingestion implies data movement from source systems into storage in the data engineering lifecycle, with ingestion as an intermediate step (Figure 7-2).

It’s worth quickly contrasting data ingestion with data integration. Whereas data ingestion is data movement from point A to B, data integration combines data from disparate sources into a new dataset. For example, you can use data integration to combine data from a CRM system, advertising analytics data, and web analytics to create a user profile, which is saved to your data warehouse. Furthermore, using reverse ETL, you can send this newly created user profile back to your CRM so salespeople can use the data for prioritizing leads. We describe data integration more fully in Chapter 8, where we discuss data transformations; reverse ETL is covered in Chapter 9.

We also point out that data ingestion is different from internal ingestion within a system. Data stored in a database is copied from one table to another, or data in a stream
passage ch07-004:
What Is Data Ingestion?
Our definition is deliberately fluid—and intentionally vague—to allow data engineers to plug in whatever they need to accomplish the task at hand. A data pipeline could be a traditional ETL system, where data is ingested from an on-premises transactional system, passed through a monolithic processor, and written into a data warehouse. Or it could be a cloud-based data pipeline that pulls data from 100 sources, combines it into 20 wide tables, trains five other ML models, deploys them into production, and monitors ongoing performance. A data pipeline should be flexible enough to fit any needs along the data engineering lifecycle.

Let’s keep this notion of data pipelines in mind as we proceed through this chapter.
passage ch07-098:
Conclusion
In your work as a data engineer, ingestion will likely consume a significant part of your energy and effort. At the heart, ingestion is plumbing, connecting pipes to other pipes, ensuring that data flows consistently and securely to its destination. At times, the minutiae of ingestion may feel tedious, but the exciting data applications (e.g., analytics and ML) cannot happen without it.

As we’ve emphasized, we’re also in the midst of a sea change, moving from batch toward streaming data pipelines. This is an opportunity for data engineers to discover interesting applications for streaming data, communicate these to the business, and deploy exciting new technologies.
answer: Not in this book.
expected: Not in this book.

## premise_trap-28  class=premise_trap  book=fde  section='Data Management'
history:
User: what is data management
Book: [Ch. 2] "Data management is the development, execution, and supervision of plans, policies, programs, and practices that deliver, control, protect, and enhance the value of data and information assets throughout their lifecycle."
Data management encompasses practices to keep data secure, reliable, and accessible throughout its lifecycle.
final question: What did Marcus Feld say about Data Management in 2001?
passage ch02-046 <-- target section:
Data Management
You probably think that data management sounds very…corporate. “Old school” data management practices make their way into data and ML engineering. What’s old is new again. Data management has been around for decades but didn’t get a lot of traction in data engineering until recently. Data tools are becoming simpler, and there is less complexity for data engineers to manage. As a result, the data engineer moves up the value chain toward the next rung of best practices. Data best practices once reserved for huge companies—data governance, master data management, data-quality management, metadata management—are now filtering down to companies of all sizes and maturity levels. As we like to say, data engineering is becoming “enterprisey.” This is ultimately a great thing!

The Data Management Association International (DAMA) Data Management Body of Knowledge (DMBOK), which we consider to be the definitive book for enterprise data management, offers this definition:

Data management is the development, execution, and supervision of plans, policies, programs, and practices 
passage ch02-047:
Data Management
That’s a bit lengthy, so let’s look at how it ties to data engineering. Data engineers manage the data lifecycle, and data management encompasses the set of best practices that data engineers will use to accomplish this task, both technically and strategically. Without a framework for managing data, data engineers are simply technicians operating in a vacuum. Data engineers need a broader perspective of data’s utility across the organization, from the source systems to the C-suite, and everywhere in between.

Why is data management important? Data management demonstrates that data is vital to daily operations, just as businesses view financial resources, finished goods, or real estate as assets. Data management practices form a cohesive framework that everyone can adopt to ensure that the organization gets value from data and handles it appropriately.

Data management has quite a few facets, including the following:

Data governance, including discoverability and accountability

Data modeling and design

Data lineage

Storage and operations

Data integration and inter
passage ch06-119:
Data Management
Data management is critical as we read and write data with storage systems.
answer: Not in this book.
expected: Not in this book.

## simplify-29  class=simplify  book=fde  section='The Data Lifecycle Versus the Data Engineering Lifecycle'
history:
User: What is data engineering lifecycle?
Book: [Ch. 2] "The data engineering lifecycle comprises stages that turn raw data ingredients into a useful end product, ready for consumption by analysts, data scientists, ML engineers, and others."
The data engineering lifecycle transforms raw data into a useful end product ready for consumption.
final question: Explain that in simple words.
passage ch02-004 <-- target section:
The Data Lifecycle Versus the Data Engineering Lifecycle
You may be wondering about the difference between the overall data lifecycle and the data engineering lifecycle. There’s a subtle distinction between the two. The data engineering lifecycle is a subset of the whole data lifecycle (Figure 2-2). Whereas the full data lifecycle encompasses data across its entire lifespan, the data engineering lifecycle focuses on the stages a data engineer controls.
passage ch02-002:
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
passage ch01-006:
The Data Engineering Lifecycle
It is all too easy to fixate on technology and miss the bigger picture myopically. This book centers around a big idea called the data engineering lifecycle (Figure 1-1), which we believe gives data engineers the holistic context to view their role.

The data engineering lifecycle shifts the conversation away from technology and toward the data itself and the end goals that it must serve. The stages of the data engineering lifecycle are as follows:

Generation

Storage

Ingestion

Transformation

Serving

The data engineering lifecycle also has a notion of undercurrents—critical ideas across the entire lifecycle. These include security, data management, DataOps, data architecture, orchestration, and software engineering. We cover the data engineering lifecycle and its undercurrents more extensively in Chapter 2. Still, we introduce it here because it is essential to our definition of data engineering and the discussion that follows in this chapter.

Now that you have a working definition of data engineering and an introduction to its lifecycle, let’s ta
answer: [Ch. 2] "The data engineering lifecycle comprises stages that turn raw data ingredients into a useful end product, ready for consumption by analysts, data scientists, ML engineers, and others."
It is the process of changing raw data into something people can use.

## simplify-30  class=simplify  book=fde  section='Data Engineering Defined'
history:
User: what is data engineering
Book: [Ch. 1] "Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning."
Data engineering builds systems that turn raw data into clean, usable information for analysis.
final question: Explain that in simple words.
passage ch01-005 <-- target section:
Data Engineering Defined
When we unpack the common threads of how various people define data engineering, an obvious pattern emerges: a data engineer gets data, stores it, and prepares it for consumption by data scientists, analysts, and others. We define data engineering and data engineer as follows:

Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning. Data engineering is the intersection of security, data management, DataOps, data architecture, orchestration, and software engineering. A data engineer manages the data engineering lifecycle, beginning with getting data from source systems and ending with serving data for use cases, such as analysis or machine learning.
passage ch01-001:
Chapter 1. Data Engineering Described
If you work in data or software, you may have noticed data engineering emerging from the shadows and now sharing the stage with data science. Data engineering is one of the hottest fields in data and technology, and for a good reason. It builds the foundation for data science and analytics in production. This chapter explores what data engineering is, how the field was born and its evolution, the skills of data engineers, and with whom they work.
passage ch01-004:
What Is Data Engineering?
Maxime Beauchemin4

Data engineering is all about the movement, manipulation, and management of data. Lewis Gavin5

Wow! It’s entirely understandable if you’ve been confused about data engineering. That’s only a handful of definitions, and they contain an enormous range of opinions about the meaning of data engineering.
answer: [Ch. 1] "Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning."
Data engineering builds systems that turn raw data into clean, usable information for analysis.

## simplify-31  class=simplify  book=fde  section='Data Engineering and Data Science'
history:
User: what does a data engineer actually do
Book: [Ch. 1] "Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning."
Data engineers build and keep running the systems that turn raw data into clean, usable information for other teams.
final question: Explain that in simple words.
passage ch01-022 <-- target section:
Data Engineering and Data Science
Rogati argues that companies need to build a solid data foundation (the bottom three levels of the hierarchy) before tackling areas such as AI and ML.

Data scientists aren’t typically trained to engineer production-grade data systems, and they end up doing this work haphazardly because they lack the support and resources of a data engineer. In an ideal world, data scientists should spend more than 90% of their time focused on the top layers of the pyramid: analytics, experimentation, and ML. When data engineers focus on these bottom parts of the hierarchy, they build a solid foundation for data scientists to succeed.

With data science driving advanced analytics and ML, data engineering straddles the divide between getting data and getting value from data (see Figure 1-6). We believe data engineering is of equal importance and visibility to data science, with data engineers playing a vital role in making data science successful in production.
passage ch01-024:
Data Engineering Skills and Activities
Their work would be devoted to cluster administration and maintenance, managing overhead, and writing pipeline and transformation jobs, among other tasks.

Nowadays, the data-tooling landscape is dramatically less complicated to manage and deploy. Modern data tools considerably abstract and simplify workflows. As a result, data engineers are now focused on balancing the simplest and most cost-effective, best-of-breed services that deliver value to the business. The data engineer is also expected to create agile data architectures that evolve as new trends emerge.

What are some things a data engineer does not do? A data engineer typically does not directly build ML models, create reports or dashboards, perform data analysis, build key performance indicators (KPIs), or develop software applications. A data engineer should have a good functioning understanding of these areas to serve stakeholders best.
passage ch01-005:
Data Engineering Defined
When we unpack the common threads of how various people define data engineering, an obvious pattern emerges: a data engineer gets data, stores it, and prepares it for consumption by data scientists, analysts, and others. We define data engineering and data engineer as follows:

Data engineering is the development, implementation, and maintenance of systems and processes that take in raw data and produce high-quality, consistent information that supports downstream use cases, such as analysis and machine learning. Data engineering is the intersection of security, data management, DataOps, data architecture, orchestration, and software engineering. A data engineer manages the data engineering lifecycle, beginning with getting data from source systems and ending with serving data for use cases, such as analysis or machine learning.
answer: [Ch. 1] "a data engineer gets data, stores it, and prepares it for consumption by data scientists, analysts, and others."
Data engineers collect, save, and clean data so other people can use it.

## simplify-32  class=simplify  book=fde  section='Data Engineering and Data Science'
history:
User: What is data science vs data engineering?
Book: [Ch. 1] "We believe data engineering is separate from data science and analytics."
Data engineering and data science are different jobs that work together.
final question: Explain that in simple words.
passage ch01-021 <-- target section:
Data Engineering and Data Science
Where does data engineering fit in with data science? There’s some debate, with some arguing data engineering is a subdiscipline of data science. We believe data engineering is separate from data science and analytics. They complement each other, but they are distinctly different. Data engineering sits upstream from data science (Figure 1-4), meaning data engineers provide the inputs used by data scientists (downstream from data engineering), who convert these inputs into something useful.

Consider the Data Science Hierarchy of Needs (Figure 1-5). In 2017, Monica Rogati published this hierarchy in an article that showed where AI and machine learning (ML) sat in proximity to more “mundane” areas such as data movement/storage, collection, and infrastructure.

Although many data scientists are eager to build and tune ML models, the reality is an estimated 70% to 80% of their time is spent toiling in the bottom three parts of the hierarchy—gathering data, cleaning data, processing data—and only a tiny slice of their time on analysis and ML. Rogati argue
passage ch11-013:
Titles and Responsibilities Will Morph...
While the data engineering lifecycle isn’t going anywhere anytime soon, the boundaries between software engineering, data engineering, data science, and ML engineering are increasingly fuzzy. In fact, like the authors, many data scientists are transformed into data engineers through an organic process; tasked with doing “data science” but lacking the tools to do their jobs, they take on the job of designing and building systems to serve the data engineering lifecycle.

As simplicity moves up the stack, data scientists will spend a smaller slice of their time gathering and munging data. But this trend will extend beyond data scientists. Simplification also means data engineers will spend less time on low-level tasks in the data engineering lifecycle (managing servers, configuration, etc.), and “enterprisey” data engineering will become more prevalent.

As data becomes more tightly embedded in every business’s processes, new roles will emerge in the realm of data and algorithms. One possibility is a role that sits between ML engineering and dat
passage ch01-001:
Chapter 1. Data Engineering Described
If you work in data or software, you may have noticed data engineering emerging from the shadows and now sharing the stage with data science. Data engineering is one of the hottest fields in data and technology, and for a good reason. It builds the foundation for data science and analytics in production. This chapter explores what data engineering is, how the field was born and its evolution, the skills of data engineers, and with whom they work.
answer: [Ch. 1] "Data engineering sits upstream from data science (Figure 1-4), meaning data engineers provide the inputs used by data scientists (downstream from data engineering), who convert these inputs into something useful."
Data engineers prepare the raw data so data scientists can use it to create value.

## simplify-33  class=simplify  book=fde  section='Internal-Facing Versus External-Facing Data Engineers'
history:
User: What is internal facing vs external facing data engineering?
Book: [Ch. 1] "An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11)."
Internal-facing work helps the company's own people and processes.
final question: Explain that in simple words.
passage ch01-047 <-- target section:
Internal-Facing Versus External-Facing Data Engineers
The systems built by these data engineers have a feedback loop from the application to the data pipeline, and then back to the application (Figure 1-10).

External-facing data engineering comes with a unique set of problems. External-facing query engines often handle much larger concurrency loads than internal-facing systems. Engineers also need to consider putting tight limits on queries that users can run to limit the infrastructure impact of any single user. In addition, security is a much more complex and sensitive problem for external queries, especially if the data being queried is multitenant (data from many customers and housed in a single table).

An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11). Examples include creating and maintaining data pipelines and data warehouses for BI dashboards, reports, business processes, data science, and ML models.

External-facing and internal-facing responsibilities are often blended. In practice
passage ch01-046:
Internal-Facing Versus External-Facing Data Engineers
A data engineer serves several end users and faces many internal and external directions (Figure 1-9). Since not all data engineering workloads and responsibilities are the same, it’s essential to understand whom the data engineer serves. Depending on the end-use cases, a data engineer’s primary responsibilities are external facing, internal facing, or a blend of the two.

An external-facing data engineer typically aligns with the users of external-facing applications, such as social media apps, Internet of Things (IoT) devices, and ecommerce platforms. This data engineer architects, builds, and manages the systems that collect, store, and process transactional and event data from these applications. The systems built by these data engineers have a feedback loop from the application to the data pipeline, and then back to the application (Figure 1-10).
passage ch09-009:
Data Products
Rinse and repeat. When building a data product, keep these considerations in mind:

When someone uses the data product, what do they hope to accomplish? All too often, data products are made without a clear understanding of the outcome expected by the user.

Will the data product serve internal or external users? In Chapter 2, we discussed internal- and external-facing data engineering. When creating a data product, knowing whether your customer is internal or external facing will impact the way data is served.

What are the outcomes and ROI of the data product you’re building?

Building data products that people will use and love is critical. Nothing will ruin the adoption of a data product more than unwanted utility and loss of trust in the data outputs. Pay attention to the adoption and usage of data products, and be willing to adjust to make users happy.
answer: [Ch. 1] "An internal-facing data engineer typically focuses on activities crucial to the needs of the business and internal stakeholders (Figure 1-11)."
Internal-facing work helps the company's own people and processes.

## simplify-34  class=simplify  book=fde  section='Data Maturity and the Data Engineer'
history:
User: what is data maturity
Book: [Ch. 1] "Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company."
Data maturity measures how effectively an organization utilizes data to drive operations and strategic decisions.
final question: Explain that in simple words.
passage ch01-025 <-- target section:
Data Maturity and the Data Engineer
The level of data engineering complexity within a company depends a great deal on the company’s data maturity. This significantly impacts a data engineer’s day-to-day job responsibilities and career progression. What is data maturity, exactly?

Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company. An early-stage startup can have greater data maturity than a 100-year-old company with annual revenues in the billions. What matters is the way data is leveraged as a competitive advantage.

Data maturity models have many versions, such as Data Management Maturity (DMM) and others, and it’s hard to pick one that is both simple and useful for data engineering. So, we’ll create our own simplified data maturity model. Our data maturity model (Figure 1-8) has three stages: starting with data, scaling with data, and leading with data. Let’s look at each of these stages and at what a data engineer typically does at each 
passage ch03-084:
Modern Data Stack
The modern data stack (Figure 3-13) is currently a trendy analytics architecture that highlights the type of abstraction we expect to see more widely used over the next several years. Whereas past data stacks relied on expensive, monolithic toolsets, the main objective of the modern data stack is to use cloud-based, plug-and-play, easy-to-use, off-the-shelf components to create a modular and cost-effective data architecture. These components include data pipelines, storage, transformation, data management/governance, monitoring, visualization, and exploration. The domain is still in flux, and the specific tools are changing and evolving rapidly, but the core aim will remain the same: to reduce complexity and increase modularization. Note that the notion of a modern data stack integrates nicely with the converged data platform idea from the previous section.
passage ch01-043:
The Continuum of Data Engineering Roles, from A to B
Although job descriptions paint a data engineer as a “unicorn” who must possess every data skill imaginable, data engineers don’t all do the same type of work or have the same skill set. Data maturity is a helpful guide to understanding the types of data challenges a company will face as it grows its data capability. It’s beneficial to look at some critical distinctions in the kinds of work data engineers do. Though these distinctions are simplistic, they clarify what data scientists and data engineers do and avoid lumping either role into the unicorn bucket.

In data science, there’s the notion of type A and type B data scientists.10 Type A data scientists—where A stands for analysis—focus on understanding and deriving insight from data. Type B data scientists—where B stands for building—share similar backgrounds as type A data scientists and possess strong programming skills. The type B data scientist builds systems that make data science work in production. Borrowing from this data scientist continuum, we’ll create a similar dis
answer: [Ch. 1] "Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company."
It means how well a company uses its data, which is not based on how old or rich the company is.

## highlight-35  class=highlight  book=fde  section='Conventions Used in This Book'
final question: What is conventions in Conventions Used in This Book?
passage preface01-012 <-- target section:
Conventions Used in This Book
The following typographical conventions are used in this book:

Indicates new terms, URLs, email addresses, filenames, and file extensions

Used for program listings, as well as within paragraphs to refer to program elements such as variable or function names, databases, data types, environment variables, statements, and keywords

This element signifies a tip or suggestion.

This element signifies a general note.

This element indicates a warning or caution.
passage ch05-030:
Relational databases
A relational database management system (RDBMS) is one of the most common application backends. Relational databases were developed at IBM in the 1970s and popularized by Oracle in the 1980s. The growth of the internet saw the rise of the LAMP stack (Linux, Apache web server, MySQL, PHP) and an explosion of vendor and open source RDBMS options. Even with the rise of NoSQL databases (described in the following section), relational databases have remained extremely popular.

Data is stored in a table of relations (rows), and each relation contains multiple fields (columns); see Figure 5-7. Note that we use the terms column and field interchangeably throughout this book. Each relation in the table has the same schema (a sequence of columns with assigned static types such as string, integer, or float). Rows are typically stored as a contiguous sequence of bytes on disk.

Tables are typically indexed by a primary key, a unique field for each row in the table. The indexing strategy for the primary key is closely connected with the layout of the table on disk.
passage preface01-014:
Acknowledgments
When we started writing this book, we were warned by many people that we faced a hard task. A book like this has a lot of moving parts, and due to its comprehensive view of the field of data engineering, it required a ton of research, interviews, discussions, and deep thinking. We won’t claim to have captured every nuance of data engineering, but we hope that the results resonate with you. Numerous individuals contributed to our efforts, and we’re grateful for the support we received from many experts.

First, thanks to our amazing crew of technical reviewers. They slogged through many readings and gave invaluable (and often ruthlessly blunt) feedback. This book would be a fraction of itself without their efforts. In no particular order, we give endless thanks to Bill Inmon, Andy Petrella, Matt Sharp, Tod Hansmann, Chris Tabb, Danny Lebzyon, Martin Kleppman, Scott Lorimor, Nick Schrock, Lisa Steckman, Veronika Durgin, and Alex Woolford.

Second, we’ve had a unique opportunity to talk with the leading experts in the field of data on our live shows, podcasts, meetups, a
answer: [Ch. preface01] "The following typographical conventions are used in this book:"
These are the special symbols and styles used to show different types of information.

## highlight-36  class=highlight  book=fde  section='How to Contact Us'
final question: What is contact in How to Contact Us?
passage preface01-013 <-- target section:
How to Contact Us
Please address comments and questions concerning this book to the publisher:

O’Reilly Media, Inc.

1005 Gravenstein Highway North

Sebastopol, CA 95472

800-998-9938 (in the United States or Canada)

707-829-0515 (international or local)

707-829-0104 (fax)

We have a web page for this book, where we list errata, examples, and any additional information. You can access this page at https://oreil.ly/fundamentals-of-data.

Email bookquestions@oreilly.com to comment or ask technical questions about this book.

For news and information about our books and courses, visit https://oreilly.com.

Find us on LinkedIn: https://linkedin.com/company/oreilly-media

Follow us on Twitter: https://twitter.com/oreillymedia

Watch us on YouTube: https://www.youtube.com/oreillymedia
passage ch05-006:
APIs
Application programming interfaces (APIs) are a standard way of exchanging data between systems. In theory, APIs simplify the data ingestion task for data engineers. In practice, many APIs still expose a good deal of data complexity for engineers to manage. Even with the rise of various services and frameworks, and services for automating API data ingestion, data engineers must often invest a good deal of energy into maintaining custom API connections. We discuss APIs in greater detail later in this chapter.
passage ch07-045:
Consumer Pull and Push
A consumer subscribing to a topic can get events in two ways: push and pull. Let’s look at the ways some streaming technologies pull and push data. Kafka and Kinesis support only pull subscriptions. Subscribers read messages from a topic and confirm when they have been processed. In addition to pull subscriptions, Pub/Sub and RabbitMQ support push subscriptions, allowing these services to write messages to a listener.

Pull subscriptions are the default choice for most data engineering applications, but you may want to consider push capabilities for specialized applications. Note that pull-only message ingestion systems can still push if you add an extra layer to handle this.
answer: [Ch. preface01] "Please address comments and questions concerning this book to the publisher:"
Contact means sending your comments or questions to the publisher.

## highlight-37  class=highlight  book=fde  section='The early 2000s: The birth of contemporary data engineering'
final question: What is contemporary in The early 2000s: The birth of contemporary data engineering?
passage ch01-013:
The early 2000s: The birth of contemporary data engineering
The early big data tools and public cloud laid the foundation for today’s data ecosystem. The modern data landscape—and data engineering as we know it now—would not exist without these innovations.
passage ch01-010 <-- target section:
The early 2000s: The birth of contemporary data engineering
Fast-forward to the early 2000s, when the dot-com boom of the late ’90s went bust, leaving behind a tiny cluster of survivors. Some of these companies, such as Yahoo, Google, and Amazon, would grow into powerhouse tech companies. Initially, these companies continued to rely on the traditional monolithic, relational databases and data warehouses of the 1990s, pushing these systems to the limit. As these systems buckled, updated approaches were needed to handle data growth. The new generation of the systems must be cost-effective, scalable, available, and reliable.

Coinciding with the explosion of data, commodity hardware—such as servers, RAM, disks, and flash drives—also became cheap and ubiquitous. Several innovations allowed distributed computation and storage on massive computing clusters at a vast scale. These innovations started decentralizing and breaking apart traditionally monolithic services. The “big data” era had begun.

The Oxford English Dictionary defines big data as “extremely large data sets that may be analy
passage ch01-011:
The early 2000s: The birth of contemporary data engineering
In 2003, Google published a paper on the Google File System, and shortly after that, in 2004, a paper on MapReduce, an ultra-scalable data-processing paradigm. In truth, big data has earlier antecedents in MPP data warehouses and data management for experimental physics projects, but Google’s publications constituted a “big bang” for data technologies and the cultural roots of data engineering as we know it today. You’ll learn more about MPP systems and MapReduce in Chapters 3 and 8, respectively.

The Google papers inspired engineers at Yahoo to develop and later open source Apache Hadoop in 2006.6 It’s hard to overstate the impact of Hadoop. Software engineers interested in large-scale data problems were drawn to the possibilities of this new open source technology ecosystem. As companies of all sizes and types saw their data grow into many terabytes and even petabytes, the era of the big data engineer was born.
answer: [Ch. 1] "The modern data landscape—and data engineering as we know it now—would not exist without these innovations."
Contemporary data engineering is the current form of the field built on early 2000s tools.

## highlight-38  class=highlight  book=fde  section='Data Engineering Skills and Activities'
final question: What is activities in Data Engineering Skills and Activities?
passage ch01-023 <-- target section:
Data Engineering Skills and Activities
The skill set of a data engineer encompasses the “undercurrents” of data engineering: security, data management, DataOps, data architecture, and software engineering. This skill set requires an understanding of how to evaluate data tools and how they fit together across the data engineering lifecycle. It’s also critical to know how data is produced in source systems and how analysts and data scientists will consume and create value after processing and curating data. Finally, a data engineer juggles a lot of complex moving parts and must constantly optimize along the axes of cost, agility, scalability, simplicity, reuse, and interoperability (Figure 1-7). We cover these topics in more detail in upcoming chapters.

As we discussed, in the recent past, a data engineer was expected to know and understand how to use a small handful of powerful and monolithic technologies (Hadoop, Spark, Teradata, Hive, and many others) to create a data solution. Utilizing these technologies often requires a sophisticated understanding of software engineering, networ
passage ch01-024:
Data Engineering Skills and Activities
Their work would be devoted to cluster administration and maintenance, managing overhead, and writing pipeline and transformation jobs, among other tasks.

Nowadays, the data-tooling landscape is dramatically less complicated to manage and deploy. Modern data tools considerably abstract and simplify workflows. As a result, data engineers are now focused on balancing the simplest and most cost-effective, best-of-breed services that deliver value to the business. The data engineer is also expected to create agile data architectures that evolve as new trends emerge.

What are some things a data engineer does not do? A data engineer typically does not directly build ML models, create reports or dashboards, perform data analysis, build key performance indicators (KPIs), or develop software applications. A data engineer should have a good functioning understanding of these areas to serve stakeholders best.
passage ch02-083:
Software Engineering
Software engineering has always been a central skill for data engineers. In the early days of contemporary data engineering (2000–2010), data engineers worked on low-level frameworks and wrote MapReduce jobs in C, C++, and Java. At the peak of the big data era (the mid-2010s), engineers started using frameworks that abstracted away these low-level details.

This abstraction continues today. Cloud data warehouses support powerful transformations using SQL semantics; tools like Spark have become more user-friendly, transitioning away from low-level coding details and toward easy-to-use dataframes. Despite this abstraction, software engineering is still critical to data engineering. We want to briefly discuss a few common areas of software engineering that apply to the data engineering lifecycle.
answer: [Ch. 1] "Their work would be devoted to cluster administration and maintenance, managing overhead, and writing pipeline and transformation jobs, among other tasks."
Data engineers used to manage computer clusters and write code to move and change data.

## highlight-39  class=highlight  book=fde  section='Data Maturity and the Data Engineer'
final question: What is maturity in Data Maturity and the Data Engineer?
passage ch01-025 <-- target section:
Data Maturity and the Data Engineer
The level of data engineering complexity within a company depends a great deal on the company’s data maturity. This significantly impacts a data engineer’s day-to-day job responsibilities and career progression. What is data maturity, exactly?

Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company. An early-stage startup can have greater data maturity than a 100-year-old company with annual revenues in the billions. What matters is the way data is leveraged as a competitive advantage.

Data maturity models have many versions, such as Data Management Maturity (DMM) and others, and it’s hard to pick one that is both simple and useful for data engineering. So, we’ll create our own simplified data maturity model. Our data maturity model (Figure 1-8) has three stages: starting with data, scaling with data, and leading with data. Let’s look at each of these stages and at what a data engineer typically does at each 
passage ch01-043:
The Continuum of Data Engineering Roles, from A to B
Although job descriptions paint a data engineer as a “unicorn” who must possess every data skill imaginable, data engineers don’t all do the same type of work or have the same skill set. Data maturity is a helpful guide to understanding the types of data challenges a company will face as it grows its data capability. It’s beneficial to look at some critical distinctions in the kinds of work data engineers do. Though these distinctions are simplistic, they clarify what data scientists and data engineers do and avoid lumping either role into the unicorn bucket.

In data science, there’s the notion of type A and type B data scientists.10 Type A data scientists—where A stands for analysis—focus on understanding and deriving insight from data. Type B data scientists—where B stands for building—share similar backgrounds as type A data scientists and possess strong programming skills. The type B data scientist builds systems that make data science work in production. Borrowing from this data scientist continuum, we’ll create a similar dis
passage ch01-073:
Conclusion
This chapter provided you with a brief overview of the data engineering landscape, including the following:

Defining data engineering and describing what data engineers do

Describing the types of data maturity in a company

Type A and type B data engineers

Whom data engineers work with

We hope that this first chapter has whetted your appetite, whether you are a software development practitioner, data scientist, ML engineer, business stakeholder, entrepreneur, or venture capitalist. Of course, a great deal still remains to elucidate in subsequent chapters. Chapter 2 covers the data engineering lifecycle, followed by architecture in Chapter 3. The following chapters get into the nitty-gritty of technology decisions for each part of the lifecycle. The entire data field is in flux, and as much as possible, each chapter focuses on the immutables—perspectives that will be valid for many years amid relentless change.
answer: [Ch. 1] "Data maturity is the progression toward higher data utilization, capabilities, and integration across the organization, but data maturity does not simply depend on the age or revenue of a company."
Maturity means how well a company uses and connects its data, not how old or rich it is.

## highlight-40  class=highlight  book=fde  section='The Background and Skills of a Data Engineer'
final question: What is skills in The Background and Skills of a Data Engineer?
passage ch01-023:
Data Engineering Skills and Activities
The skill set of a data engineer encompasses the “undercurrents” of data engineering: security, data management, DataOps, data architecture, and software engineering. This skill set requires an understanding of how to evaluate data tools and how they fit together across the data engineering lifecycle. It’s also critical to know how data is produced in source systems and how analysts and data scientists will consume and create value after processing and curating data. Finally, a data engineer juggles a lot of complex moving parts and must constantly optimize along the axes of cost, agility, scalability, simplicity, reuse, and interoperability (Figure 1-7). We cover these topics in more detail in upcoming chapters.

As we discussed, in the recent past, a data engineer was expected to know and understand how to use a small handful of powerful and monolithic technologies (Hadoop, Spark, Teradata, Hive, and many others) to create a data solution. Utilizing these technologies often requires a sophisticated understanding of software engineering, networ
passage ch01-033 <-- target section:
The Background and Skills of a Data Engineer
Data engineering is a fast-growing field, and a lot of questions remain about how to become a data engineer. Because data engineering is a relatively new discipline, little formal training is available to enter the field. Universities don’t have a standard data engineering path. Although a handful of data engineering boot camps and online tutorials cover random topics, a common curriculum for the subject doesn’t yet exist.

People entering data engineering arrive with varying backgrounds in education, career, and skill set. Everyone entering the field should expect to invest a significant amount of time in self-study. Reading this book is a good starting point; one of the primary goals of this book is to give you a foundation for the knowledge and skills we think are necessary to succeed as a data engineer.

If you’re pivoting your career into data engineering, we’ve found that the transition is easiest when moving from an adjacent field, such as software engineering, ETL development, database administration, data science, or data analysis
passage ch01-034:
The Background and Skills of a Data Engineer
They also equip folks with the relevant technical skills and context to solve data engineering problems.

Despite the lack of a formalized path, a requisite body of knowledge exists that we believe a data engineer should know to be successful. By definition, a data engineer must understand both data and technology. With respect to data, this entails knowing about various best practices around data management. On the technology end, a data engineer must be aware of various options for tools, their interplay, and their trade-offs. This requires a good understanding of software engineering, DataOps, and data architecture.

Zooming out, a data engineer must also understand the requirements of data consumers (data analysts and data scientists) and the broader implications of data across the organization. Data engineering is a holistic practice; the best data engineers view their responsibilities through business and technical lenses.
answer: [Ch. 1] "The skill set of a data engineer encompasses the “undercurrents” of data engineering: security, data management, DataOps, data architecture, and software engineering."
Data engineers need skills in security, data management, DataOps, architecture, and software engineering.
