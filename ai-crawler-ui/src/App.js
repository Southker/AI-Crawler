import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import jsPDF from 'jspdf';

function App() {
  const [url, setUrl] = useState('');
  const [currentChatId, setCurrentChatId] = useState(null);
  const [allChats, setAllChats] = useState({}); // Store all conversations
  const [currentTaskId, setCurrentTaskId] = useState(null);
  const [status, setStatus] = useState('Ready');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [theme, setTheme] = useState('light');
  const [renamingChatId, setRenamingChatId] = useState(null);
  const [newChatTitle, setNewChatTitle] = useState('');
  const [starredChats, setStarredChats] = useState(new Set());
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [emailData, setEmailData] = useState({ email: '', reportName: '', message: '' });
  const [emailingResponse, setEmailingResponse] = useState(null);
  const messagesEndRef = useRef(null);

  // Get current chat history
  const chatHistory = currentChatId && allChats[currentChatId] 
    ? allChats[currentChatId].messages 
    : [];

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatHistory]);

  // Load chats from localStorage on mount
  useEffect(() => {
    const savedChats = localStorage.getItem('ai_crawler_chats');
    if (savedChats) {
      const parsed = JSON.parse(savedChats);
      setAllChats(parsed);
      // Set the most recent chat as current
      const chatIds = Object.keys(parsed);
      if (chatIds.length > 0) {
        const mostRecent = chatIds.sort((a, b) => 
          parsed[b].timestamp - parsed[a].timestamp
        )[0];
        setCurrentChatId(mostRecent);
      }
    } else {
      // Create first chat
      const newChatId = Date.now().toString();
      const newChat = {
        id: newChatId,
        messages: [],
        timestamp: Date.now(),
        title: 'New Chat'
      };
      setAllChats({ [newChatId]: newChat });
      setCurrentChatId(newChatId);
    }

    // Load theme preference
    const savedTheme = localStorage.getItem('ai_crawler_theme') || 'light';
    setTheme(savedTheme);
    document.documentElement.setAttribute('data-theme', savedTheme);

    // Load starred chats
    const savedStarred = localStorage.getItem('ai_crawler_starred');
    if (savedStarred) {
      setStarredChats(new Set(JSON.parse(savedStarred)));
    }
  }, []);

  // Save chats to localStorage whenever they change
  useEffect(() => {
    if (Object.keys(allChats).length > 0) {
      localStorage.setItem('ai_crawler_chats', JSON.stringify(allChats));
    }
  }, [allChats]);

  // Update chat messages
  const updateCurrentChat = (newMessages) => {
    if (!currentChatId) return;
    
    setAllChats(prev => {
      const updated = { ...prev };
      updated[currentChatId] = {
        ...updated[currentChatId],
        messages: newMessages,
        timestamp: Date.now(),
        // Update title based on first URL
        title: newMessages.length > 0 && newMessages[0].type === 'user'
          ? newMessages[0].content.substring(0, 40) + (newMessages[0].content.length > 40 ? '...' : '')
          : 'New Chat'
      };
      return updated;
    });
  };

  // Start crawling
  const startCrawl = async () => {
    const trimmedUrl = url.trim();
    
    // Client-side URL validation
    if (!trimmedUrl) {
      alert('Please enter a valid URL.');
      return;
    }

    // Check if it's a valid URL format
    // eslint-disable-next-line no-useless-escape
    const urlPattern = /^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$/;
    if (!urlPattern.test(trimmedUrl)) {
      setStatus('❌ Invalid URL');
      const errorMessages = [
        { type: 'user', content: trimmedUrl },
        { type: 'ai', content: `Invalid URL format: "${trimmedUrl}"\n\nPlease enter a valid URL like:\n• https://example.com\n• http://example.com\n• example.com` }
      ];
      updateCurrentChat([...chatHistory, ...errorMessages]);
      setUrl('');
      return;
    }

    // Ensure URL has a scheme
    let finalUrl = trimmedUrl;
    if (!trimmedUrl.startsWith('http://') && !trimmedUrl.startsWith('https://')) {
      finalUrl = 'https://' + trimmedUrl;
    }

    // Add user message to current chat
    const newMessages = [...chatHistory, { type: 'user', content: finalUrl }];
    updateCurrentChat(newMessages);
    setStatus('Validating URL...');

    // Quick connectivity check via backend
    try {
      const checkRes = await fetch('/validate-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: finalUrl }),
      });
      
      const checkData = await checkRes.json();
      
      if (!checkData.valid) {
        setStatus('❌ Invalid URL');
        const errorMessage = { 
          type: 'ai', 
          content: checkData.error || 'Could not connect to the website. Please check the URL and try again.'
        };
        updateCurrentChat([...newMessages, errorMessage]);
        setUrl('');
        return;
      }
    } catch (error) {
      // If validation endpoint fails, continue anyway (fallback)
      console.warn('URL validation failed, proceeding with crawl');
    }

    setStatus('Starting crawl...');

    try {
      const res = await fetch('/crawl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: finalUrl }),
      });
      const data = await res.json();
      setCurrentTaskId(data.task_id);
      setUrl(''); // Clear input
    } catch (error) {
      setStatus('Failed to start crawl');
      console.error('Crawl error:', error);
    }
  };

  // Check crawl status
  const checkStatus = async (taskId) => {
    try {
      const res = await fetch(`/status/${taskId}`);
      const data = await res.json();
      setStatus(data.status);

      const isComplete = 
        data.status.includes('✅') ||
        data.status.includes('Analysis complete') ||
        data.status.includes('finished') ||
        data.status.includes('stopped') ||
        data.status.includes('Stopped by User') ||
        data.status.includes('Failed');

      if (isComplete) {
        if (data.result) {
          const newMessages = [...chatHistory, { type: 'ai', content: data.result }];
          updateCurrentChat(newMessages);
        } else {
          const newMessages = [...chatHistory, { type: 'ai', content: data.status }];
          updateCurrentChat(newMessages);
        }
        setCurrentTaskId(null);
      } else {
        setTimeout(() => checkStatus(taskId), 2000);
      }
    } catch (error) {
      setStatus('Error checking status');
      setCurrentTaskId(null);
      console.error('Status check error:', error);
    }
  };

  useEffect(() => {
    if (currentTaskId) {
      checkStatus(currentTaskId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTaskId]);

  // Stop crawling
  const stopCrawl = async () => {
    if (!currentTaskId) return;

    try {
      const res = await fetch(`/stop/${currentTaskId}`, { method: 'POST' });
      const data = await res.json();
      setStatus(data.status);
      setCurrentTaskId(null);
    } catch (error) {
      setStatus('Failed to stop crawl');
      console.error('Stop error:', error);
    }
  };

  // Start new chat
  const newChat = () => {
    const newChatId = Date.now().toString();
    const newChatData = {
      id: newChatId,
      messages: [],
      timestamp: Date.now(),
      title: 'New Chat'
    };
    
    setAllChats(prev => ({ ...prev, [newChatId]: newChatData }));
    setCurrentChatId(newChatId);
    setStatus('Ready');
    setCurrentTaskId(null);
    setUrl('');
  };

  // Switch to a different chat
  const switchChat = (chatId) => {
    setCurrentChatId(chatId);
    setStatus('Ready');
    setCurrentTaskId(null);
    setUrl('');
  };

  // Helper function to strip HTML tags
  const stripHtml = (html) => {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim();
  };

  // Download chat as PDF
  const downloadAsPDF = () => {
  if (chatHistory.length === 0) {
    alert('No content to download');
    return;
  }

  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 15;
  const maxLineWidth = pageWidth - (margin * 2);
  let yPosition = margin;

  const checkPageBreak = (additionalSpace = 5) => {
    if (yPosition + additionalSpace > pageHeight - margin) {
      doc.addPage();
      yPosition = margin;
      return true;
    }
    return false;
  };

  doc.setFont('courier');
  doc.setFontSize(8);
  doc.setTextColor(0, 0, 0);

  chatHistory.forEach((msg, index) => {
    if (msg.type === 'user') {
      // USER section
      checkPageBreak(10);
      const userLines = doc.splitTextToSize(`USER: ${msg.content}`, maxLineWidth);
      userLines.forEach(line => {
        checkPageBreak(4);
        doc.text(line, margin, yPosition);
        yPosition += 4;
      });
      yPosition += 3;
    } else {
      // AI ANALYSIS section
      checkPageBreak(10);
      doc.text('AI ANALYSIS:', margin, yPosition);
      yPosition += 5;

      // Get plain text
      const plainText = stripHtml(msg.content);
      
      // Split by lines and render each
      const lines = plainText.split('\n');
      
      lines.forEach(line => {
        if (line.trim() === '') {
          yPosition += 2;
          return;
        }

        checkPageBreak(4);
        
        // Split long lines to fit page width
        const wrappedLines = doc.splitTextToSize(line, maxLineWidth);
        wrappedLines.forEach(wLine => {
          checkPageBreak(4);
          doc.text(wLine, margin, yPosition);
          yPosition += 4;
        });
      });
    }

    // Separator between messages
    if (index < chatHistory.length - 1) {
      checkPageBreak(8);
      yPosition += 3;
      doc.text('-'.repeat(80), margin, yPosition);
      yPosition += 5;
    }
  });

  // Simple footer
  const pageCount = doc.internal.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.text(`Page ${i} of ${pageCount}`, pageWidth / 2, pageHeight - 8, { align: 'center' });
  }

  doc.save(`ai-crawler-analysis-${Date.now()}.pdf`);
};

 // Download individual response as PDF - Keep formatting, remove emojis only
  const downloadResponse = (response, index) => {
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 15;
  const maxLineWidth = pageWidth - (margin * 2);
  let yPosition = margin;

  // Helper to check if new page is needed
  const checkPageBreak = (additionalSpace = 5) => {
    if (yPosition + additionalSpace > pageHeight - margin) {
      doc.addPage();
      yPosition = margin;
      return true;
    }
    return false;
  };

  // Remove only emojis, keep everything else
  const removeEmojis = (text) => {
    return text
      .replace(/[\u{1F300}-\u{1F9FF}]/gu, '') // Emoticons
      .replace(/[\u{2600}-\u{26FF}]/gu, '') // Misc symbols
      .replace(/[\u{2700}-\u{27BF}]/gu, '') // Dingbats
      .replace(/[\u{1F000}-\u{1F02F}]/gu, '') // Mahjong tiles
      .replace(/[\u{1F0A0}-\u{1F0FF}]/gu, '') // Playing cards
      .replace(/[\u{1F100}-\u{1F64F}]/gu, '') // Enclosed characters
      .replace(/[\u{1F680}-\u{1F6FF}]/gu, '') // Transport symbols
      .replace(/[\u{1F900}-\u{1F9FF}]/gu, '') // Supplemental symbols
      .replace(/[\u{1FA00}-\u{1FA6F}]/gu, '') // Extended symbols
      .replace(/[\u{1FA70}-\u{1FAFF}]/gu, '') // More symbols
      .replace(/[\u{FE00}-\u{FE0F}]/gu, '') // Variation selectors
      .replace(/[\u{200D}]/gu, '') // Zero width joiner
      .trim();
  };

  // Detect if line should be bold (headers, important sections)
  const shouldBeBold = (line) => {
    const trimmed = removeEmojis(line.trim());
    
    // Lines with all equals or dashes (separators aren't bold)
    // eslint-disable-next-line no-useless-escape
    if (/^[=\-]{10,}$/.test(trimmed)) {
      return false;
    }
    
    // Lines ending with colon - likely headers
    if (trimmed.endsWith(':')) {
      // Remove parenthetical content and count uppercase
      const withoutParens = trimmed.replace(/\([^)]*\)/g, '').trim();
      const withoutColon = withoutParens.slice(0, -1).trim();
      const uppercaseChars = withoutColon.replace(/[^A-Z]/g, '').length;
      const totalLetters = withoutColon.replace(/[^A-Za-z]/g, '').length;
      
      // If mostly uppercase (ignoring content in parentheses)
      if (totalLetters > 0 && uppercaseChars / totalLetters > 0.7) {
        return true;
      }
    }
    
    // Don't bold lines that start with bullet points or common prefixes
    if (/^[•✓✗◆▪▫→]/.test(trimmed) || trimmed.startsWith('http')) {
      return false;
    }
    
    // Fully uppercase lines with decent length AND containing spaces (multi-word headers)
    const lettersOnly = trimmed.replace(/[^A-Za-z]/g, '');
    const hasSpaces = trimmed.includes(' ');
    
    // Only bold if it's a multi-word uppercase line (headers), not single words like "HTML" or "AJAX"
    if (lettersOnly.length > 10 && lettersOnly === lettersOnly.toUpperCase() && hasSpaces) {
      return true;
    }
    
    return false;
  };

     // Set initial font
  doc.setFont('courier', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(0, 0, 0);

  // Add title at the top (bold)
  doc.setFont('courier', 'bold');
  doc.text(`AI CRAWLER - RESPONSE #${index + 1}`, margin, yPosition);
  yPosition += 5;
  
  // Add separator line (normal font)
  doc.setFont('courier', 'normal');
  doc.text('='.repeat(80), margin, yPosition);
  yPosition += 8;

  // Get plain text from HTML
  const plainText = stripHtml(response.content);
  
  // Split by lines and render each
  const lines = plainText.split('\n');
  
  lines.forEach(line => {
    const cleanedLine = removeEmojis(line);
    
    // Handle empty lines
    if (cleanedLine.trim() === '') {
      yPosition += 2;
      return;
    }

    checkPageBreak(4);
    
    // Set font weight based on content
    if (shouldBeBold(line)) {
      doc.setFont('courier', 'bold');
    } else {
      doc.setFont('courier', 'normal');
    }
    
    // Split long lines to fit page width
    const wrappedLines = doc.splitTextToSize(cleanedLine, maxLineWidth);
    wrappedLines.forEach(wLine => {
      checkPageBreak(4);
      doc.text(wLine, margin, yPosition);
      yPosition += 4;
    });
  });

  // Footer
  doc.setFont('courier', 'normal');
  const pageCount = doc.internal.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.text(`Page ${i} of ${pageCount}`, pageWidth / 2, pageHeight - 8, { align: 'center' });
  }

  doc.save(`ai-crawler-response-${index + 1}-${Date.now()}.pdf`);
  };

  // Toggle theme
  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    localStorage.setItem('ai_crawler_theme', newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  };

  // Rename chat
  const startRenameChat = (chatId, currentTitle) => {
    setRenamingChatId(chatId);
    setNewChatTitle(currentTitle);
  };

  const saveRename = () => {
    if (!renamingChatId || !newChatTitle.trim()) return;
    
    setAllChats(prev => {
      const updated = { ...prev };
      updated[renamingChatId] = {
        ...updated[renamingChatId],
        title: newChatTitle.trim()
      };
      return updated;
    });
    
    setRenamingChatId(null);
    setNewChatTitle('');
  };

  const cancelRename = () => {
    setRenamingChatId(null);
    setNewChatTitle('');
  };

  // Toggle star on chat
  const toggleStar = (chatId) => {
    setStarredChats(prev => {
      const newStarred = new Set(prev);
      if (newStarred.has(chatId)) {
        newStarred.delete(chatId);
      } else {
        newStarred.add(chatId);
      }
      localStorage.setItem('ai_crawler_starred', JSON.stringify([...newStarred]));
      return newStarred;
    });
  };

  // Delete chat
  const deleteChat = (chatId) => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm('Are you sure you want to delete this chat?')) return;
    
    setAllChats(prev => {
      const updated = { ...prev };
      delete updated[chatId];
      return updated;
    });

    // If deleting current chat, switch to another
    if (chatId === currentChatId) {
      const remaining = Object.keys(allChats).filter(id => id !== chatId);
      if (remaining.length > 0) {
        setCurrentChatId(remaining[0]);
      } else {
        // Create new chat if none left
        newChat();
      }
    }

    // Remove from starred
    if (starredChats.has(chatId)) {
      toggleStar(chatId);
    }
  };

  // Open email modal
  const openEmailModal = (response, index) => {
    setEmailingResponse({ content: response.content, index });
    setEmailData({ 
      email: '', 
      reportName: `AI Crawler Report #${index + 1}`, 
      message: '' 
    });
    setShowEmailModal(true);
  };

  // Send email (mailto approach)
  const sendEmail = () => {
    if (!emailData.email || !emailData.email.includes('@')) {
      alert('Please enter a valid email address');
      return;
    }

    // Strip HTML for email body
    const plainText = stripHtml(emailingResponse.content);

    const subject = encodeURIComponent(emailData.reportName);
    const body = encodeURIComponent(
      `${emailData.message ? emailData.message + '\n\n' : ''}` +
      `--- AI CRAWLER REPORT ---\n\n` +
      `${plainText}\n\n` +
      `---\nGenerated by AI Crawler`
    );

    window.location.href = `mailto:${emailData.email}?subject=${subject}&body=${body}`;
    
    setShowEmailModal(false);
    setEmailingResponse(null);
  };

  // Handle Enter key
  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!currentTaskId) {
        startCrawl();
      }
    }
  };

  // Get sorted chat list (starred first)
  const sortedChats = Object.values(allChats)
    .sort((a, b) => {
      // Starred chats first
      const aStarred = starredChats.has(a.id);
      const bStarred = starredChats.has(b.id);
      if (aStarred && !bStarred) return -1;
      if (!aStarred && bStarred) return 1;
      // Then by timestamp
      return b.timestamp - a.timestamp;
    });

  return (
    <div className="app-root">
      {/* Topbar */}
      <div className="topbar">
        <div className="top-left">
          <button 
            className="hamburger" 
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          >
            ☰
          </button>
          <div className="brand">AI Crawler</div>
        </div>
        <div className="top-right">
          {chatHistory.length > 0 && (
            <button className="icon-btn" onClick={downloadAsPDF} title="Download as PDF">
              📥
            </button>
          )}
          <button 
            className="icon-btn" 
            onClick={toggleTheme}
            title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
          >
            {theme === 'light' ? '🌙' : '☀️'}
          </button>
        </div>
      </div>

      {/* Sidebar */}
      <div className={`sidebar ${isSidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-inner">
          <h3 className="sb-title">Chat History</h3>
          <div className="history">
            {sortedChats.length === 0 ? (
              <div style={{ color: 'var(--muted)', fontSize: '14px' }}>
                No history yet
              </div>
            ) : (
              sortedChats.map((chat) => (
                <div 
                  key={chat.id} 
                  className={`history-item ${chat.id === currentChatId ? 'active' : ''}`}
                  style={{
                    background: chat.id === currentChatId 
                      ? 'rgba(75, 114, 255, 0.2)' 
                      : 'var(--glass)',
                    borderLeft: chat.id === currentChatId 
                      ? '3px solid var(--accent)' 
                      : '3px solid transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px'
                  }}
                >
                  {renamingChatId === chat.id ? (
                    <input
                      type="text"
                      value={newChatTitle}
                      onChange={(e) => setNewChatTitle(e.target.value)}
                      onKeyPress={(e) => {
                        if (e.key === 'Enter') saveRename();
                        if (e.key === 'Escape') cancelRename();
                      }}
                      onBlur={saveRename}
                      autoFocus
                      style={{
                        flex: 1,
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text)',
                        fontSize: '14px',
                        outline: 'none',
                        padding: '0'
                      }}
                    />
                  ) : (
                    <>
                      <span 
                        onClick={() => switchChat(chat.id)}
                        style={{ 
                          flex: 1, 
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                      >
                        {starredChats.has(chat.id) && '⭐ '}
                        {chat.title}
                      </span>
                      <div style={{ display: 'flex', gap: '4px' }}>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleStar(chat.id);
                          }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: starredChats.has(chat.id) ? '#fbbf24' : 'var(--muted)',
                            cursor: 'pointer',
                            padding: '4px',
                            fontSize: '14px',
                            display: 'flex',
                            alignItems: 'center',
                            opacity: 0.7,
                            transition: 'opacity 0.2s'
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
                          onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
                          title={starredChats.has(chat.id) ? 'Unstar' : 'Star'}
                        >
                          {starredChats.has(chat.id) ? '⭐' : '☆'}
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            startRenameChat(chat.id, chat.title);
                          }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--muted)',
                            cursor: 'pointer',
                            padding: '4px',
                            fontSize: '14px',
                            display: 'flex',
                            alignItems: 'center',
                            opacity: 0.6,
                            transition: 'opacity 0.2s'
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
                          onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                          title="Rename chat"
                        >
                          ✏️
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteChat(chat.id);
                          }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--danger)',
                            cursor: 'pointer',
                            padding: '4px',
                            fontSize: '14px',
                            display: 'flex',
                            alignItems: 'center',
                            opacity: 0.6,
                            transition: 'opacity 0.2s'
                          }}
                          onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
                          onMouseLeave={(e) => e.currentTarget.style.opacity = '0.6'}
                          title="Delete chat"
                        >
                          🗑️
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))
            )}
          </div>

          <div className="plan-block" style={{ padding: '0 16px 16px 16px' }}>
            <button className="newchat" onClick={newChat}>
              + New Chat
            </button>
          </div>
      </div>   {/* sidebar-inner */}
      </div>   {/* sidebar */}

      {/* Chat Area */}
      <div className="chat-area">
        <div className="messages-wrap">
          {chatHistory.length === 0 ? (
            <div className="welcome">
              <h2>Welcome to AI Crawler</h2>
              <p>Enter a URL below to analyze the website's technologies</p>
            </div>
          ) : (
            chatHistory.map((msg, idx) => (
              <div
                key={idx}
                style={{ 
                  display: 'flex', 
                  flexDirection: 'column',
                  alignItems: msg.type === 'user' ? 'flex-end' : 'flex-start',
                  gap: '8px'
                }}
              >
                <div
                  className={`bubble ${
                    msg.type === 'user' ? 'bubble-user' : 'bubble-ai'
                  }`}
                >
                  {msg.type === 'ai' ? (
                    <div 
                      style={{ 
                        margin: 0, 
                        wordBreak: 'break-word',
                        fontSize: '13px',
                        fontFamily: 'monospace',
                        maxHeight: '600px',
                        overflow: 'auto',
                        lineHeight: '1.6'
                      }}
                      dangerouslySetInnerHTML={{ __html: msg.content }}
                    />
                  ) : (
                    msg.content
                  )}
                </div>
                {msg.type === 'ai' && (
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => downloadResponse(msg, idx)}
                      style={{
                        background: 'var(--glass)',
                        border: '1px solid var(--border)',
                        padding: '4px 10px',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        color: 'var(--muted)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--panel)';
                        e.currentTarget.style.borderColor = 'var(--accent)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'var(--glass)';
                        e.currentTarget.style.borderColor = 'var(--border)';
                      }}
                      title="Download this response as PDF"
                    >
                      📥 Download PDF
                    </button>
                    <button
                      onClick={() => openEmailModal(msg, idx)}
                      style={{
                        background: 'var(--glass)',
                        border: '1px solid var(--border)',
                        padding: '4px 10px',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        color: 'var(--muted)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        transition: 'all 0.2s'
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--panel)';
                        e.currentTarget.style.borderColor = 'var(--accent)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'var(--glass)';
                        e.currentTarget.style.borderColor = 'var(--border)';
                      }}
                      title="Email this response"
                    >
                      ✉️ Email
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="input-bar">
          <textarea
            className="input-box"
            placeholder="Enter URL to analyze (e.g., https://example.com)..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={currentTaskId !== null}
            rows={1}
          />
          <div className="input-actions">
            {currentTaskId ? (
              <button className="btn stop" onClick={stopCrawl}>
                Stop
              </button>
            ) : (
              <button className="btn send" onClick={startCrawl}>
                Analyze
              </button>
            )}
          </div>
        </div>

        {/* Status */}
        <div style={{ 
          textAlign: 'center', 
          color: 'var(--muted)', 
          fontSize: '13px',
          marginTop: '8px'
        }}>
          Status: {status}
        </div>
      </div>

      {/* Settings Modal */}
      {isModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Settings</h3>
            <p>Configure your AI Crawler settings here.</p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setIsModalOpen(false)}>
                Cancel
              </button>
              <button className="btn primary" onClick={() => setIsModalOpen(false)}>
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Email Modal */}
      {showEmailModal && (
        <div className="modal-backdrop" onClick={() => setShowEmailModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Email Report</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginTop: '16px' }}>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--muted)', display: 'block', marginBottom: '4px' }}>
                  Recipient Email *
                </label>
                <input
                  type="email"
                  value={emailData.email}
                  onChange={(e) => setEmailData({ ...emailData, email: e.target.value })}
                  placeholder="user@example.com"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    fontSize: '14px'
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--muted)', display: 'block', marginBottom: '4px' }}>
                  Report Name
                </label>
                <input
                  type="text"
                  value={emailData.reportName}
                  onChange={(e) => setEmailData({ ...emailData, reportName: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    fontSize: '14px'
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--muted)', display: 'block', marginBottom: '4px' }}>
                  Message (optional, max 150 chars)
                </label>
                <textarea
                  value={emailData.message}
                  onChange={(e) => {
                    if (e.target.value.length <= 150) {
                      setEmailData({ ...emailData, message: e.target.value });
                    }
                  }}
                  placeholder="Add a short message..."
                  rows={3}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border)',
                    background: 'var(--input-bg)',
                    color: 'var(--input-text)',
                    fontSize: '14px',
                    resize: 'none',
                    fontFamily: 'inherit'
                  }}
                />
                <div style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '4px', textAlign: 'right' }}>
                  {emailData.message.length}/150
                </div>
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowEmailModal(false)}>
                Cancel
              </button>
              <button className="btn primary" onClick={sendEmail}>
                Send Email
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
