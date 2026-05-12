// docs/src/components/HomepageFeatures.tsx
import React, { ReactNode } from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css'; // Make sure this path is correct

type FeatureItem = {
  title: string;
  Svg: React.ComponentType<React.ComponentProps<'svg'>>;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'AI-Powered Writing',
    Svg: require('@site/static/img/undraw_artificial-intelligence_fuvd.svg').default, // Replace with a suitable SVG
    description: (
      <>
        Leverage the power of OpenAI's language models to generate outlines,
        characters, worldbuilding details, and even full chapter drafts.
      </>
    ),
  },
  {
    title: 'Multi-Agent System',
    Svg: require('@site/static/img/undraw_meet-the-team_pp46.svg').default, // Replace with a suitable SVG
    description: (
      <>
        LibriScribe uses a modular, multi-agent architecture. Each agent
        specializes in a specific task, making the process efficient and
        extensible.
      </>
    ),
  },
  {
    title: 'Simple & Advanced Modes',
    Svg: require('@site/static/img/undraw_in-thought_xa50.svg').default, // Replace with suitable SVG
    description: (
      <>
        Choose between a streamlined Simple Mode for quick drafts or an
        Advanced Mode for fine-grained control over every step of the writing
        process.
      </>
    ),
  },
  {
    title: 'Comprehensive Editing',
    Svg: require('@site/static/img/undraw_file-bundle_oaof.svg').default, // Replace with suitable SVG
    description: (
        <>
          Refine your chapters with agents dedicated to content review, style
          editing, fact-checking, and plagiarism detection.
        </>
    ),
  },
    {
    title: 'Research Capabilities',
    Svg: require('@site/static/img/undraw_researching_5qj6.svg').default, // Replace with suitable SVG
    description: (
        <>
          Utilize the integrated research agent to gather information and
            enrich your writing.
        </>
    ),
  },
    {
      title: 'Markdown & PDF Output',
      Svg: require('@site/static/img/undraw_ai-code-generation_imyw.svg').default, //Replace
      description:(
        <>
          Format your completed manuscript into a polished Markdown or PDF
            document, ready for publication or sharing.
        </>
      ),
    },
];

function Feature({ title, Svg, description }: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center">
        <Svg className={styles.featureSvg} role="img" />
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}