%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% © DRL CSAIL MIT 2022 - All RIGHTS RESERVED.
% AUTHORS: RAMIN HASANI and ALEXANDER AMINI

% License: Creative Commons license 
% Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{arxivtmpl}[2022/05/31 arXiv Template (forked from MIT CSAIL)]




\LoadClass[11pt]{article}

\input{packages}

%% 章节编号一律不带句点（subsection / subsubsection 走此默认 label）
\titlelabel{\thetitle\quad}

%% 章节标题统一 Lato Heavy sans（eb 字重 = 比 bold 再粗一号），按层级递减字号
\titleformat{\section}
  {\sffamily\fontseries{eb}\Large\selectfont}
  {\thesection}{1em}{}
  []
\titlespacing*{\section}{0pt}{\baselineskip}{0.3\baselineskip}

\titleformat{\subsection}
  {\sffamily\fontseries{eb}\large\selectfont}
  {\thesubsection}{1em}{}
\titlespacing*{\subsection}{0pt}{0.9\baselineskip}{-0.15\baselineskip}

\titleformat{\subsubsection}[runin]
  {\sffamily\fontseries{eb}\normalsize\selectfont}
  {\thesubsubsection}{1em}{}[\quad]

\titleformat{\paragraph}[runin]
  {\sffamily\fontseries{eb}\normalsize\selectfont}
  {}{0em}{}[\quad]

%% ToC 间距：section 条目间保持宽间距，section 内 subsection 用正常行距
\setlength{\cftbeforesecskip}{0.8em}
\setlength{\cftbeforesubsecskip}{0pt}
%% Contents 标题与 section 同款字体
\renewcommand{\cfttoctitlefont}{\sffamily\fontseries{eb}\Large\selectfont}
%% 标题下间距对齐 section（取值偏大因 titlesec 把行距算进去；末项抵消首条目的 \cftbeforesecskip）
\renewcommand{\cftaftertoctitle}{\par\vspace{0.8\baselineskip}%
  \vspace{0.65\baselineskip}\vspace{-\cftbeforesecskip}}

\captionsetup[figure]{font=small}
\captionsetup[table]{font=small}


%%========  Author and affiliation ========
\setcounter{Maxaffil}{0}
\setlength{\affilsep}{0.2em}
\makeatletter
\renewcommand\AB@affilsepx{, \protect\Affilfont}
\makeatother
\renewcommand\Authands{ and }
\makeatletter
\renewcommand\AB@authnote[1]{\,\textsuperscript{\normalfont#1}}
\renewcommand\AB@affilnote[1]{\,\textsuperscript{\normalfont#1}}
\makeatother



\renewcommand*{\thefootnote}{\fnsymbol{footnote}}

%% 页面四周间距：对齐 MAI 技术报告（US Letter；左右≈77.5pt，上≈91pt，下≈105pt）
\geometry{
  letterpaper,
  hmargin=77.5pt,                 % 左右边距各 ~1.08in -> textwidth ~457pt (16.1cm)
  top=91pt,                       % 正文顶端距纸顶（正文页无 running header）
  textheight=596pt,               % 下边距自动 ~105pt
  headheight=34pt, headsep=8pt,
  footskip=30pt                   % 页码距正文底 ~30pt
}

\newcommand{\titlefont}{\normalfont\bfseries\fontsize{21}{26}\selectfont}

\renewenvironment{abstract}
 {
  \list{}{%
    \setlength{\leftmargin}{0mm}%
    \setlength{\rightmargin}{\leftmargin}%
  }%
  \item\relax}
  
  
\makeatletter

%% \authornote{...} 在作者列表下方紧贴显示一行 8pt sans（contribution markers / correspondence）
%% 留空（不调用）则不显示该行
\newcommand{\@authornote}{}
\newcommand{\authornote}[1]{\gdef\@authornote{#1}}

\renewcommand{\maketitle}{\bgroup\setlength{\parindent}{0pt}
\begin{flushleft}
  {\titlefont\bfseries\@title\par}\vspace*{19pt}

  {\@author}
  \ifx\@authornote\@empty\else
    \par\vspace{0.4em}
    {\sffamily\fontsize{8}{10}\selectfont\@authornote\par}
  \fi
\end{flushleft}\egroup
}

%% 首页：无页眉、无页脚
\fancypagestyle{firstpagestyle}{
    \fancyhf{}
    \renewcommand{\headrulewidth}{0pt}
    \renewcommand{\footrulewidth}{0pt}
    }

%% 正文页：仅右下角页码
\fancypagestyle{fancy}{
    \fancyhf{}
    \renewcommand{\headrulewidth}{0pt}
    \renewcommand{\footrulewidth}{0pt}
    \rfoot{\thepage}
    }

\pagestyle{fancy}

\makeatother




\renewcommand{\figurename}{\textbf{Figure}}
\renewcommand{\tablename}{\textbf{Table}}
\renewcommand{\thetable}{\textbf{\arabic{table}}}
\renewcommand{\thefigure}{\textbf{\arabic{figure}}}


\newtheorem{definition}{Definition}
\newtheorem{lemma}{Lemma}
\newtheorem{proposition}{Proposition}
\newtheorem{theorem}{Theorem}
\newtheorem{remark}{Remark}
\newtheorem{corollary}{Corollary}
\newtheorem{example}{Example}

%% appendix：section 编号 A/B/C，figure / table / equation 按 section 编号（A.1）
\newcommand{\beginsupplement}{%
    \appendix

    \setcounter{section}{0}%
    \renewcommand{\thesection}{\Alph{section}}%

    \setcounter{figure}{0}%
    \renewcommand{\thefigure}{\thesection.\arabic{figure}}%
    \numberwithin{figure}{section}%

    \setcounter{table}{0}%
    \renewcommand{\thetable}{\thesection.\arabic{table}}%
    \numberwithin{table}{section}%

    \setcounter{equation}{0}%
    \renewcommand{\theequation}{\thesection.\arabic{equation}}%
    \numberwithin{equation}{section}%
}

\setlength{\parindent}{0pt}
\setlength{\parskip}{0.5\baselineskip}