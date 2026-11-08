import * as story from './story';
import * as twin from './twin';
import * as compare from './compare';

export const SCENES: Record<string, React.FC<any>> = {...story, ...twin, ...compare};
