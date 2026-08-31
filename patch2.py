import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Add `isTyping` state
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
content = content.replace(advance_old, advance_new)

# 3. Update the useEffect for autoPlay
effect_old = """useEffect(() => {
      let timer;
      if (view === 'neg' && session && session.status === 'active' && !session.awaiting_human && autoPlay && !loading) {
        timer = setTimeout(() => {
          advance(session.id);
        }, 2000);
      }
      return () => clearTimeout(timer);
    }, [view, session, autoPlay, loading]);"""

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
      } else if (!autoPlay && isTyping) {
         setIsTyping(false);
      }
      return () => clearTimeout(timer);
    }, [view, session, autoPlay, loading, isTyping]);"""
content = content.replace(effect_old, effect_new)

# 4. Update the render condition for the typing indicator
indicator_old = """${loading && autoPlay ? html`
                    <div className="bubble-wrap" style=${{alignSelf: session.turn === 'buyer' ? 'flex-start' : 'flex-end'}}>
                       <div className="bubble" style=${{background: 'transparent', padding: '0.5rem'}}>
                         <div className="typing-indicator"><span></span><span></span><span></span></div>
                       </div>
                    </div>
                  ` : null}"""
# Note: Since we used sed earlier, it might just be loading && autoPlay or something else.
# Let's use regex to find the exact block.
