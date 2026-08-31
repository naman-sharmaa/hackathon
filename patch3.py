import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Add `isTyping` state
if "const [isTyping, setIsTyping] = useState(false);" not in content:
    content = content.replace(
        "const [loading, setLoading] = useState(false);",
        "const [loading, setLoading] = useState(false);\n    const [isTyping, setIsTyping] = useState(false);"
    )

# 2. Update `advance` function to clear `isTyping`
advance_old = """const advance = async (currentSessionId) => {
      setLoading(true);"""
advance_new = """const advance = async (currentSessionId) => {
      setIsTyping(false);
      setLoading(true);"""
if advance_old in content:
    content = content.replace(advance_old, advance_new)

# 3. Use regex to replace the useEffect block safely
effect_pattern = re.compile(
    r"useEffect\(\(\) => \{\n\s*let timer;\n\s*if \(view === 'neg'.*?return \(\) => clearTimeout\(timer\);\n\s*\}, \[view, session, autoPlay, loading\]\);",
    re.DOTALL
)

effect_new = """useEffect(() => {
      let timer;
      if (view === 'neg' && session && session.status === 'active' && !session.awaiting_human && autoPlay && !loading) {
        if (!isTyping) {
          setIsTyping(true);
        } else {
          timer = setTimeout(() => {
            advance(session.id);
          }, 2000);
        }
      } else if (isTyping) {
         setIsTyping(false);
      }
      return () => clearTimeout(timer);
    }, [view, session, autoPlay, loading, isTyping]);"""

content = effect_pattern.sub(effect_new, content)

with open('frontend/index.html', 'w') as f:
    f.write(content)

