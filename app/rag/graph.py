from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from app.rag.pipeline import LegalRAG
from langchain_openai import ChatOpenAI
from app.core.config import settings

class RetrievalState(TypedDict, total=False):
    query: str
    documents: list
    attempts: int
    answer: str

def build_retrieval_graph(rag: LegalRAG):
    async def retrieve(state):
        return {"documents": await rag.search(state["query"]), "attempts": state.get("attempts", 0) + 1}
    def route(state):
        return "generate" if state.get("documents") else ("done" if state.get("attempts", 0) >= 2 else "retry")
    async def generate(state):
        context = "\n\n".join(f"[근거 {i}] {d.content}" for i, d in enumerate(state["documents"], 1))
        prompt = ("다음 근거만 사용해 한국어로 답하세요. 근거가 부족하면 모른다고 답하고, "
                  "법률 자문이 아닌 정보 제공임을 명시하세요.\n\n" + context + "\n\n질문: " + state["query"])
        response = await ChatOpenAI(model=settings.MODEL_NAME, api_key=settings.OPENAI_API_KEY,
                                    temperature=0).ainvoke(prompt)
        return {"answer": response.content}
    graph = StateGraph(RetrievalState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", route, {"retry": "retrieve", "generate": "generate", "done": END})
    graph.add_edge("generate", END)
    return graph.compile()
