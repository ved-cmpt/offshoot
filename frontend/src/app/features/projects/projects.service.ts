import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface Project {
  id: string;
  name: string;
  description: string | null;
  source_kind: 'BUNDLED' | 'UPLOAD';
  status: 'IMPORTED' | 'ANALYZING' | 'ANALYZED' | 'FAILED';
  created_at: string;
  source_file_count: number;
  source_line_count: number;
}

export interface ProjectPage {
  items: Project[];
  total: number;
  limit: number;
  offset: number;
}

@Injectable({ providedIn: 'root' })
export class ProjectsService {
  private readonly http = inject(HttpClient);

  list(): Observable<ProjectPage> {
    return this.http.get<ProjectPage>('/api/v1/projects');
  }
}
