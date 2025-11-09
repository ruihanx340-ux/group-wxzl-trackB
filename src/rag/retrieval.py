from openai import OpenAI
from .index import search

def answer_with_citations(user_q: str, unit_id: str = None, k: int = 4, model: str = "gpt-4o-mini") -> str:
    ctx = search(user_q, unit_id=unit_id, k=k)
    if not ctx:
        return "I couldn't find this in your documents. Please upload the relevant lease or rules."
    blocks, cites = [], []
    for i, c in enumerate(ctx, 1):
        blocks.append(f"[{i}] ({c['file']} p.{c['page']})\n{c['text']}")
        cites.append(f"{c['file']} p.{c['page']}")
    sys = ("You are a property assistant. Only answer using the CONTEXT. "
           "If not in the context, say you can't find it. Always include citations.")
    usr = "QUESTION:\n" + user_q + "\n\nCONTEXT:\n" + ("\n\n".join(blocks))
    client = OpenAI()
    rs = client.responses.create(
        model=model,
        input=[{"role": "system", "content": sys}, {"role": "user", "content": usr}]
    )
    ans = rs.output[0].content[0].text
    tail = "References: [" + "; ".join(dict.fromkeys(cites)) + "]"
    return ans + "\n\n" + tail
