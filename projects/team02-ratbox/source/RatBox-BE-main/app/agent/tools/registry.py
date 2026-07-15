"""react_agent(Phase A, 후보 검색)에 bind할 Tool 목록.

classify_missing_ingredients/find_substitutes는 Phase B(선택 후 상세)에서 에이전트의
자율 선택 없이 결정론적으로 직접 호출하므로 여기 포함하지 않는다.
"""

from app.agent.tools.recipe_tools import execute_sql, generate_sql
from app.agent.tools.substitute_tools import find_substitutes

ALL_TOOLS = [generate_sql, execute_sql]

# B흐름(조리 중 음성질의)에서 react_agent가 자율 선택할 수 있는 Tool 목록.
VOICE_TOOLS = [find_substitutes]
