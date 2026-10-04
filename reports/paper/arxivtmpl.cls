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

\titlelabel{\thetitle\quad}

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

\setlength{\cftbeforesecskip}{0.8em}
\setlength{\cftbeforesubsecskip}{0pt}
\renewcommand{\cfttoctitlefont}{\sffamily\fontseries{eb}\Large\selectfont}
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

\geometry{
  letterpaper,
  hmargin=77.5pt,
  top=91pt,
  textheight=596pt,
  headheight=34pt, headsep=8pt,
  footskip=30pt
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

\fancypagestyle{firstpagestyle}{
    \fancyhf{}
    \renewcommand{\headrulewidth}{0pt}
    \renewcommand{\footrulewidth}{0pt}
    }

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