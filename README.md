# Tenant Support Assistant (Track B)

A small assistant for tenants and property managers. The goal is to centralize common actions such as "inquiring about contract terms / reporting maintenance issues / following up on processing progress" in a simple web page. 
The project is currently a prototype based on Streamlit and is already available for online access and demonstration (not a screenshot-based demo, but one that can be interacted with). 
---

The problem we want to solve 
The process in reality is usually like this: 
Tenants keep asking repetitive questions such as "When is the rent due?", "Can I keep a pet?" and "How do I report a leak?".
The property manager has to rummage through the contract, management regulations and chat records everywhere before replying one by one.
Repair requests end up scattered across WhatsApp, WeChat, phone calls and notes on paper. 
What we hope to achieve is: 
1. Tenants can directly ask questions on the webpage (similar to a customer service chat box).
2. The chat assistant can answer based on existing contracts/management regulations or identify "This is a repair issue".
3. Repair issues can be automatically transformed into work orders, recorded, prioritized, and their status tracked. 
This is the core objective of Track B (landlord/property management assistant). 
---

## 2. Completed Features (Sprint 2 Status) 
The current online version already has these practical and functional features: 
### 2.1 Chat (Chat Assistant) 
Users can input natural language questions, such as: 
* “When is the rent due for unit A-101?”
* “There is water leaking under my kitchen sink.”
The system will generate responses using a large model (via the OpenAI API). If the question is related to maintenance, such as water leakage, air conditioner malfunction, or noise disturbance, the assistant will categorize the content as a maintenance request and prompt the creation of a work order. For questions regarding contracts or regulations, the assistant will attempt to provide explanatory answers. 
Note: Currently, the model directly answers the questions. It has not yet been able to quote the exact page and article number from the contract. This feature will be added in the next stage of the RAG process. 
### 2.2 Knowledge Base (Contract Document Library) 
* You can upload PDFs, such as leases, house rules, building policies, etc.
* Each document will record: 
* Corresponding unit_id (e.g. A-101)
* Document type (lease / house_rules / other)
* Effective
