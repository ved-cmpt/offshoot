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

  /** A new project from a .zip of COBOL sources. The server checks it, and never runs it. */
  create(name: string, archive: File): Observable<Project> {
    const form = new FormData();
    form.append('name', name);
    form.append('archive', archive, archive.name);
    return this.http.post<Project>('/api/v1/projects', form);
  }
}
