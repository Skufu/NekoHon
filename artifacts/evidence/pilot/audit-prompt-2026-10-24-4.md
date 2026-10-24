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
